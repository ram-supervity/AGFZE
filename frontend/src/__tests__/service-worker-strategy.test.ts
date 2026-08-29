import { describe, expect, it } from "vitest";

import {
  CACHE_TTL_SECONDS,
  NEVER_CACHED_SEGMENTS,
  STRATEGY,
  cacheNames,
  isApplicationCache,
  isFresh,
  isMutating,
  routeKey,
  strategyFor,
} from "@/service-worker/strategy";

const APP = "https://command-centre.agfze.test";
const API = "https://api.agfze.test";
const ORIGINS = { appOrigin: APP, apiOrigin: API };

function request(url: string, init: { method?: string; mode?: string; destination?: string } = {}) {
  return { url, method: init.method ?? "GET", mode: init.mode, destination: init.destination };
}

describe("the network-only rule for anything that changes something", () => {
  it("never caches a mutating request, whatever it is or wherever it goes", () => {
    const methods = ["POST", "PATCH", "PUT", "DELETE"];
    const paths = [
      "/api/v1/transactions/abc/submit",
      "/api/v1/approvals/abc/decide",
      "/api/v1/approvals/bulk-decide",
      "/api/v1/transactions/abc/generate-draft",
      "/api/v1/documents/abc/confirm",
      "/api/v1/exceptions/abc/resolve",
      "/api/v1/transactions",
      "/api/v1/notifications/push-subscribe",
      // Even a path the strategy would happily cache on a GET.
      "/api/v1/dashboards/summary",
      "/transactions",
    ];
    for (const method of methods) {
      for (const path of paths) {
        expect(strategyFor(request(`${API}${path}`, { method }), ORIGINS), `${method} ${path}`).toBe(
          STRATEGY.NETWORK_ONLY,
        );
        expect(strategyFor(request(`${APP}${path}`, { method }), ORIGINS), `${method} ${path}`).toBe(
          STRATEGY.NETWORK_ONLY,
        );
      }
    }
  });

  it("names the safety-critical actions explicitly, so a GET-shaped variant is still refused", () => {
    for (const segment of ["submit", "decide", "generate-draft", "confirm", "resolve"]) {
      expect(NEVER_CACHED_SEGMENTS).toContain(segment);
      expect(
        strategyFor(request(`${API}/api/v1/transactions/abc/${segment}`), ORIGINS),
        segment,
      ).toBe(STRATEGY.NETWORK_ONLY);
    }
  });

  it("treats every method other than GET as mutating", () => {
    expect(isMutating("GET")).toBe(false);
    expect(isMutating("get")).toBe(false);
    for (const method of ["POST", "PATCH", "PUT", "DELETE", "HEAD"]) {
      expect(isMutating(method), method).toBe(true);
    }
  });

  it("keeps authentication off the cache entirely", () => {
    expect(strategyFor(request(`${APP}/api/auth/session`), ORIGINS)).toBe(STRATEGY.NETWORK_ONLY);
  });
});

describe("the strategy table", () => {
  it("serves the app shell and static build output cache-first", () => {
    for (const path of [
      "/_next/static/chunks/main-abc.js",
      "/_next/static/css/app.css",
      "/icons/icon-192.png",
      "/manifest.webmanifest",
      "/offline",
    ]) {
      expect(strategyFor(request(`${APP}${path}`), ORIGINS), path).toBe(STRATEGY.CACHE_FIRST);
    }
  });

  it("serves list and summary reads stale-while-revalidate", () => {
    for (const path of [
      "/api/v1/transactions",
      "/api/v1/exceptions",
      "/api/v1/approvals",
      "/api/v1/shipments",
      "/api/v1/documents",
      "/api/v1/dashboards/summary",
      "/api/v1/dashboards/kpis",
    ]) {
      expect(strategyFor(request(`${API}${path}`), ORIGINS), path).toBe(
        STRATEGY.STALE_WHILE_REVALIDATE,
      );
    }
    // And the screens themselves, which are the same routes with the API prefix removed.
    expect(strategyFor(request(`${APP}/exceptions`, { mode: "navigate" }), ORIGINS)).toBe(
      STRATEGY.STALE_WHILE_REVALIDATE,
    );
  });

  it("serves single-record detail reads network-first", () => {
    for (const path of [
      "/api/v1/transactions/9f1",
      "/api/v1/transactions/purchase/9f1",
      "/api/v1/exceptions/9f1",
      "/api/v1/approvals/9f1",
      "/api/v1/shipments/9f1",
      "/api/v1/documents/9f1",
    ]) {
      expect(strategyFor(request(`${API}${path}`), ORIGINS), path).toBe(STRATEGY.NETWORK_FIRST);
    }
    expect(
      strategyFor(request(`${APP}/transactions/sales/9f1`, { mode: "navigate" }), ORIGINS),
    ).toBe(STRATEGY.NETWORK_FIRST);
  });

  it("treats a query string as part of the same list route", () => {
    expect(strategyFor(request(`${API}/api/v1/exceptions?status=open&page=2`), ORIGINS)).toBe(
      STRATEGY.STALE_WHILE_REVALIDATE,
    );
  });

  it("passes an unrecognised read through to the network rather than caching by default", () => {
    for (const path of ["/api/v1/jobs/abc/status", "/api/v1/audit", "/internal/files/abc"]) {
      expect(strategyFor(request(`${API}${path}`), ORIGINS), path).toBe(STRATEGY.NETWORK_ONLY);
    }
  });

  it("never touches a third-party origin", () => {
    expect(strategyFor(request("https://fonts.gstatic.com/font.woff2"), ORIGINS)).toBe(
      STRATEGY.NETWORK_ONLY,
    );
    expect(strategyFor(request("https://analytics.example.com/collect"), ORIGINS)).toBe(
      STRATEGY.NETWORK_ONLY,
    );
  });

  it("never serves a stale Next.js flight or data response", () => {
    expect(strategyFor(request(`${APP}/_next/data/build/exceptions.json`), ORIGINS)).toBe(
      STRATEGY.NETWORK_ONLY,
    );
    expect(strategyFor(request(`${APP}/exceptions?_rsc=abc`, { mode: "navigate" }), ORIGINS)).toBe(
      STRATEGY.NETWORK_ONLY,
    );
  });
});

describe("routeKey", () => {
  it("reduces an API path and the screen showing it to the same rule", () => {
    expect(routeKey("/api/v1/exceptions/123")).toBe("/exceptions/123");
    expect(routeKey("/exceptions/123")).toBe("/exceptions/123");
    expect(routeKey("/approvals/")).toBe("/approvals");
  });
});

describe("the fifteen-minute ceiling on cached responses", () => {
  const now = new Date("2026-08-28T12:00:00Z").getTime();

  it("defaults to fifteen minutes", () => {
    expect(CACHE_TTL_SECONDS).toBe(900);
  });

  it("serves what is inside the window and drops what is not", () => {
    expect(isFresh("2026-08-28T11:59:00Z", now)).toBe(true);
    expect(isFresh("2026-08-28T11:45:01Z", now)).toBe(true);
    expect(isFresh("2026-08-28T11:44:00Z", now)).toBe(false);
    expect(isFresh(null, now)).toBe(false);
    expect(isFresh("not a date", now)).toBe(false);
  });
});

describe("cache versioning", () => {
  it("keys every cache to the deployed build, so a release invalidates the last one", () => {
    const first = cacheNames("build-one");
    const second = cacheNames("build-two");
    expect(first.precache).not.toBe(second.precache);
    expect(first.runtime).not.toBe(second.runtime);
    expect(isApplicationCache(first.precache)).toBe(true);
    expect(isApplicationCache(second.runtime)).toBe(true);
    expect(isApplicationCache("some-other-app-cache")).toBe(false);
  });
});
