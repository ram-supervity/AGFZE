import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { beforeAll, describe, expect, it, vi } from "vitest";

/**
 * The generated worker, executed.
 *
 * These assertions are made against `public/sw.js` itself - the file a browser would actually
 * run, built by the same script `npm run build` runs - rather than against the source modules it
 * was assembled from. The rule that matters most in this step is a negative one ("a mutating
 * request is never written to or served from cache"), and a negative is only worth proving
 * against the artefact that ships.
 */

const ROOT = join(__dirname, "..", "..");
const APP_ORIGIN = "https://command-centre.agfze.test";

class FakeCache {
  entries = new Map<string, Response>();
  puts: unknown[] = [];

  async put(request: unknown, response: Response) {
    this.puts.push(request);
    this.entries.set(String(request), response);
  }

  async match(request: unknown) {
    return this.entries.get(String(request)) ?? undefined;
  }

  async delete(request: unknown) {
    return this.entries.delete(String(request));
  }
}

class FakeCacheStorage {
  caches = new Map<string, FakeCache>();

  async open(name: string) {
    if (!this.caches.has(name)) this.caches.set(name, new FakeCache());
    return this.caches.get(name)!;
  }

  async match(request: unknown, options?: { cacheName?: string }) {
    if (options?.cacheName) {
      return (await this.open(options.cacheName)).match(request);
    }
    for (const cache of this.caches.values()) {
      const hit = await cache.match(request);
      if (hit) return hit;
    }
    return undefined;
  }

  async keys() {
    return [...this.caches.keys()];
  }

  async delete(name: string) {
    return this.caches.delete(name);
  }

  get allPuts() {
    return [...this.caches.values()].flatMap((cache) => cache.puts);
  }
}

interface Harness {
  listeners: Map<string, (event: never) => void>;
  cacheStorage: FakeCacheStorage;
  fetchMock: ReturnType<typeof vi.fn>;
  showNotification: ReturnType<typeof vi.fn>;
}

function loadWorker(source: string): Harness {
  const listeners = new Map<string, (event: never) => void>();
  const cacheStorage = new FakeCacheStorage();
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  const showNotification = vi.fn(async () => undefined);

  const self = {
    location: { origin: APP_ORIGIN },
    addEventListener: (type: string, listener: (event: never) => void) => {
      listeners.set(type, listener);
    },
    skipWaiting: async () => undefined,
    clients: {
      claim: async () => undefined,
      matchAll: async () => [],
      openWindow: async () => undefined,
    },
    registration: { showNotification },
  };

  const factory = new Function(
    "self",
    "caches",
    "fetch",
    "Response",
    "Headers",
    "URL",
    `${source}\nreturn true;`,
  );
  factory(self, cacheStorage, fetchMock, Response, Headers, URL);
  return { listeners, cacheStorage, fetchMock, showNotification };
}

function fetchEvent(request: Record<string, unknown>) {
  const captured: { responded: boolean; promise: Promise<Response> | null } = {
    responded: false,
    promise: null,
  };
  return {
    event: {
      request,
      respondWith(promise: Promise<Response>) {
        captured.responded = true;
        captured.promise = promise;
      },
      waitUntil() {},
    },
    captured,
  };
}

let source: string;
let harness: Harness;

beforeAll(() => {
  execFileSync("node", [join(ROOT, "scripts", "build-sw.mjs")], { cwd: ROOT });
  source = readFileSync(join(ROOT, "public", "sw.js"), "utf8");
});

describe("the generated service worker", () => {
  beforeAll(() => {
    harness = loadWorker(source);
  });

  it("registers the handlers a push-capable, offline-capable worker needs", () => {
    expect([...harness.listeners.keys()].sort()).toEqual(
      ["activate", "fetch", "install", "message", "notificationclick", "push"].sort(),
    );
  });

  it("does not intercept a mutating request at all, so nothing about it can be cached", async () => {
    for (const method of ["POST", "PATCH", "PUT", "DELETE"]) {
      const { event, captured } = fetchEvent({
        url: `${APP_ORIGIN}/api/v1/approvals/abc/decide`,
        method,
        headers: new Headers({ Authorization: "Bearer a-real-looking-token" }),
      });
      harness.listeners.get("fetch")!(event as never);
      expect(captured.responded, method).toBe(false);
    }
    // And nothing reached storage as a side effect.
    expect(harness.cacheStorage.allPuts).toEqual([]);
  });

  it("registers no background sync anywhere - a mutation is never queued for replay", () => {
    // The prohibition, checked against the shipped file. Client-side replay of an approval
    // decision is a governance boundary this platform has held since its first description, not
    // an unbuilt feature, so the shape of it must not exist in the worker at all.
    expect(source).not.toContain('addEventListener("sync"');
    expect(source).not.toContain('addEventListener("periodicsync"');
    expect(source).not.toMatch(/SyncManager|backgroundSync|registration\.sync|\.sync\.register/);
    expect(source).not.toContain("IndexedDB");
    expect(source).not.toContain("indexedDB");
  });

  it("caches a list read under a plain URL, so no Authorization header enters storage", async () => {
    const fresh = loadWorker(source);
    const { event, captured } = fetchEvent({
      url: `${APP_ORIGIN}/api/v1/exceptions?status=open`,
      method: "GET",
      headers: new Headers({ Authorization: "Bearer a-real-looking-token" }),
    });
    fresh.listeners.get("fetch")!(event as never);
    expect(captured.responded).toBe(true);
    await captured.promise;

    const puts = fresh.cacheStorage.allPuts;
    expect(puts.length).toBeGreaterThan(0);
    for (const key of puts) {
      // A string, never a Request - a Request would carry the caller's headers into the cache.
      expect(typeof key).toBe("string");
      expect(String(key)).not.toContain("Bearer");
    }
  });

  it("stamps what it stores with the moment it was stored", async () => {
    const fresh = loadWorker(source);
    const { event, captured } = fetchEvent({
      url: `${APP_ORIGIN}/api/v1/approvals`,
      method: "GET",
      headers: new Headers(),
    });
    fresh.listeners.get("fetch")!(event as never);
    await captured.promise;

    const cached = await fresh.cacheStorage.match(`${APP_ORIGIN}/api/v1/approvals`);
    expect(cached).toBeDefined();
    expect(cached!.headers.get("x-agfze-cached-at")).toBeTruthy();
  });

  it("falls back to the precached offline page for a navigation with no network", async () => {
    const fresh = loadWorker(source);
    const precache = await fresh.cacheStorage.open(
      (await fresh.cacheStorage.keys()).find((name) => name.includes("precache")) ??
        "agfze-precache-test",
    );
    await precache.put("/offline", new Response("<h1>You are offline</h1>", { status: 200 }));
    fresh.fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const { event, captured } = fetchEvent({
      url: `${APP_ORIGIN}/exceptions/9f1`,
      method: "GET",
      mode: "navigate",
      destination: "document",
      headers: new Headers(),
    });
    fresh.listeners.get("fetch")!(event as never);
    const response = await captured.promise;
    expect(await response!.text()).toContain("You are offline");
  });

  it("shows a push as a notification carrying its deep link", async () => {
    const fresh = loadWorker(source);
    const waits: Promise<unknown>[] = [];
    fresh.listeners.get("push")!({
      data: {
        json: () => ({
          title: "Decision waiting on you",
          body: "I2626-B1 is awaiting a decision.",
          url: "/approvals/9f1",
          type: "approval.requested",
        }),
      },
      waitUntil: (promise: Promise<unknown>) => waits.push(promise),
    } as never);
    await Promise.all(waits);

    expect(fresh.showNotification).toHaveBeenCalledWith(
      "Decision waiting on you",
      expect.objectContaining({
        body: "I2626-B1 is awaiting a decision.",
        data: { url: "/approvals/9f1" },
      }),
    );
  });

  it("empties every cache it owns when the app asks it to on sign-out", async () => {
    const fresh = loadWorker(source);
    (await fresh.cacheStorage.open("agfze-runtime-x")).put(
      `${APP_ORIGIN}/api/v1/transactions`,
      new Response("[]"),
    );
    (await fresh.cacheStorage.open("agfze-precache-x")).put("/offline", new Response("x"));

    const waits: Promise<unknown>[] = [];
    fresh.listeners.get("message")!({
      data: { type: "CLEAR_CACHES" },
      waitUntil: (promise: Promise<unknown>) => waits.push(promise),
    } as never);
    await Promise.all(waits);

    expect(await fresh.cacheStorage.keys()).toEqual([]);
  });
});
