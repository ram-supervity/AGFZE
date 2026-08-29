import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api-client";
import { resetOfflineState, setOnline } from "@/lib/offline-state";
import { STRATEGY, strategyFor } from "@/service-worker/strategy";

/**
 * The ninth end-to-end scenario: governance while disconnected.
 *
 * The other eight live in the backend suite because that is where the deal travels. This one
 * belongs here, because the promise it tests is a property of the browser: a mutating action
 * taken with no connection is *refused*, visibly, and is never queued for later replay.
 *
 * The distinction is the whole point. A queued approval is worse than a refused one: it leaves
 * somebody believing they have decided something, and then applies that decision hours later
 * against a record that has since moved on. So the test asserts three things together - the
 * request never leaves, the user is told plainly, and nothing anywhere retains it.
 */

const ORIGINS = { appOrigin: "https://app.agfze.test", apiOrigin: "https://api.agfze.test" };

const MUTATIONS = [
  { method: "POST", url: `${ORIGINS.apiOrigin}/api/v1/approvals/abc/decide` },
  { method: "POST", url: `${ORIGINS.apiOrigin}/api/v1/approvals/bulk-decide` },
  { method: "POST", url: `${ORIGINS.apiOrigin}/api/v1/transactions/abc/submit` },
  { method: "POST", url: `${ORIGINS.apiOrigin}/api/v1/exceptions/abc/resolve` },
  { method: "PATCH", url: `${ORIGINS.apiOrigin}/api/v1/transactions/abc/fields` },
  { method: "POST", url: `${ORIGINS.apiOrigin}/api/v1/documents/upload` },
  { method: "DELETE", url: `${ORIGINS.apiOrigin}/api/v1/notifications/push-subscribe` },
];

const originalFetch = global.fetch;

beforeEach(() => {
  resetOfflineState();
});

afterEach(() => {
  global.fetch = originalFetch;
  resetOfflineState();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("a governance action taken offline", () => {
  it("is refused before it is attempted, and the network is never touched", async () => {
    const attempted = vi.fn();
    global.fetch = attempted as unknown as typeof fetch;
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    setOnline(false);

    await expect(
      apiFetch("/approvals/abc/decide", {
        method: "POST",
        body: { decision: "approved" },
        accessToken: "token",
      }),
    ).rejects.toBeInstanceOf(ApiError);

    expect(attempted).not.toHaveBeenCalled();
  });

  it("tells the user the action has not been taken, rather than that something went wrong", async () => {
    global.fetch = vi.fn() as unknown as typeof fetch;
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    setOnline(false);

    let error: unknown;
    try {
      await apiFetch("/transactions/abc/submit", {
        method: "POST",
        body: {},
        accessToken: "token",
      });
    } catch (thrown) {
      error = thrown;
    }

    expect(error).toBeInstanceOf(ApiError);
    const refusal = error as ApiError;
    expect(refusal.code).toBe("offline");
    // The message has to say the action did not happen. "Network error" would leave somebody
    // reasonably believing it might have.
    expect(refusal.message.toLowerCase()).toMatch(/nothing has been sent/);
  });

  it("still attempts a read, because the worker may have a cached copy to answer with", async () => {
    const attempted = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { items: [] } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    global.fetch = attempted as unknown as typeof fetch;
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://api.agfze.test/api/v1");
    Object.defineProperty(window.navigator, "onLine", { configurable: true, value: false });
    setOnline(false);

    await apiFetch("/transactions", { accessToken: "token" });

    expect(attempted).toHaveBeenCalledTimes(1);
  });
});

describe("the service worker's side of the same promise", () => {
  it.each(MUTATIONS)("routes $method $url straight to the network only", (request) => {
    expect(strategyFor(request, ORIGINS)).toBe(STRATEGY.NETWORK_ONLY);
  });

  it("has no branch that could ever cache or replay a mutation", () => {
    const root = join(process.cwd(), "src", "service-worker");
    const runtime = readFileSync(join(root, "runtime.js"), "utf8");
    const strategy = readFileSync(join(root, "strategy.js"), "utf8");

    for (const source of [runtime, strategy]) {
      // The APIs a replay queue would be built out of. None of them appears.
      expect(source).not.toMatch(/SyncManager|registration\.sync|\.sync\.register|periodicSync/);
      expect(source).not.toMatch(/indexedDB|openDatabase/i);
    }

    // And every cache write is keyed by a URL string, never by a Request - which is what makes
    // it structurally impossible for an Authorization header to end up in storage.
    const puts = runtime.match(/cache\.put\(([^,]+),/g) ?? [];
    expect(puts.length).toBeGreaterThan(0);
    for (const put of puts) {
      expect(put).not.toMatch(/cache\.put\(\s*request/);
    }
  });

  it("serves the offline page for a navigation it cannot answer, and nothing more", () => {
    const navigation = {
      method: "GET",
      url: `${ORIGINS.appOrigin}/approvals`,
      mode: "navigate",
      destination: "document",
    };
    // A list route, so it may be served stale while it refreshes - a read, never a write.
    expect(strategyFor(navigation, ORIGINS)).toBe(STRATEGY.STALE_WHILE_REVALIDATE);

    const decide = { method: "POST", url: `${ORIGINS.appOrigin}/approvals/abc/decide` };
    expect(strategyFor(decide, ORIGINS)).toBe(STRATEGY.NETWORK_ONLY);
  });
});
