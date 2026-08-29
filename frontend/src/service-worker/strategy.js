/**
 * Which caching strategy a request gets, decided in one pure function.
 *
 * This module is deliberately plain JavaScript with no imports and no browser API on it. The
 * build script inlines it into `public/sw.js`, and the test suite imports it directly - so the
 * rules the service worker actually applies at runtime are the same object the tests assert on,
 * rather than a second description of them that has to be kept in agreement.
 *
 * The table below is the one from this platform's specification, implemented literally:
 *
 *   precached shell / static build assets ....... cache-first
 *   list and summary GET reads .................. stale-while-revalidate
 *   single-record detail GET reads .............. network-first, cache only on a real failure
 *   EVERY mutating request ...................... network-only, never cached, never queued
 *   navigation with no network and no cache ..... the precached /offline route
 *
 * The network-only rule is absolute and is checked first, before anything else can classify a
 * request. There is no branch anywhere in this file that can put a mutating request into a cache,
 * and none that can replay one later: offline support on this platform is read-only, which is a
 * governance boundary rather than an unfinished feature.
 */

export const STRATEGY = {
  CACHE_FIRST: "cache-first",
  STALE_WHILE_REVALIDATE: "stale-while-revalidate",
  NETWORK_FIRST: "network-first",
  NETWORK_ONLY: "network-only",
};

/** How long a cached API or page response may still be served. Fifteen minutes. */
export const CACHE_TTL_SECONDS = 15 * 60;

/** Stamped onto every response served from, or written to, the runtime cache. */
export const CACHED_AT_HEADER = "x-agfze-cached-at";

/**
 * Path segments that are never cached and never served from cache, whatever the method says.
 *
 * The method check already refuses every POST, PATCH, PUT and DELETE. This list is the second
 * lock on the same door, naming the safety-critical actions explicitly - submit, decide,
 * generate-draft, confirm, resolve - so that a future GET-shaped variant of any of them cannot
 * quietly become cacheable.
 */
export const NEVER_CACHED_SEGMENTS = [
  "submit",
  "decide",
  "bulk-decide",
  "generate-draft",
  "confirm",
  "resolve",
  "retry",
  "complete-manual",
  "refresh",
  "mark-all-read",
  "push-subscribe",
  "override",
  "reclassify",
  "match",
  "upload",
  "export",
];

/** Prefixes that are the application shell: hashed build output and static brand assets. */
const STATIC_PREFIXES = ["/_next/static/", "/icons/", "/fonts/"];
const STATIC_FILES = ["/manifest.webmanifest", "/favicon.ico", "/offline"];

/**
 * Collections. A list is the screen a user opens to see what is waiting for them, and serving a
 * slightly stale one instantly while it refreshes underneath is the right trade for a queue.
 */
const LIST_PATHS = [
  "/transactions",
  "/exceptions",
  "/approvals",
  "/shipments",
  "/documents",
  "/requests",
  "/inbox",
  "/reports",
  "/notifications",
  "/dashboards/summary",
  "/dashboards/kpis",
  "/dashboard",
  "/analytics",
];

/**
 * Single records. A detail screen is where somebody decides something, so it goes to the network
 * first every time and only falls back to a cached copy on a genuine network failure - never on a
 * refusal, a 404 or a 500, each of which is the server telling the truth about the record.
 */
const DETAIL_PATTERNS = [
  /^\/transactions\/(purchase|sales|fa)\/[^/]+$/,
  /^\/transactions\/[^/]+$/,
  /^\/exceptions\/[^/]+$/,
  /^\/approvals\/[^/]+$/,
  /^\/shipments\/[^/]+$/,
  /^\/documents\/[^/]+$/,
  /^\/requests\/[^/]+$/,
  /^\/inbox\/[^/]+$/,
  /^\/reports\/[^/]+$/,
];

function normalisePath(pathname) {
  if (pathname.length > 1 && pathname.endsWith("/")) return pathname.slice(0, -1);
  return pathname;
}

/**
 * The API prefix stripped off, so `/api/v1/exceptions/123` classifies as `/exceptions/123` - the
 * same path the screen showing it has. One set of rules covers both.
 */
export function routeKey(pathname) {
  const path = normalisePath(pathname);
  const match = path.match(/^\/api\/v\d+(\/.*)?$/);
  return match ? normalisePath(match[1] || "/") : path;
}

export function isMutating(method) {
  return (method || "GET").toUpperCase() !== "GET";
}

export function isNeverCached(pathname) {
  const segments = routeKey(pathname).split("/").filter(Boolean);
  return segments.some((segment) => NEVER_CACHED_SEGMENTS.includes(segment));
}

export function isStaticAsset(pathname) {
  const path = normalisePath(pathname);
  return (
    STATIC_PREFIXES.some((prefix) => path.startsWith(prefix)) || STATIC_FILES.includes(path)
  );
}

export function isListRoute(pathname) {
  return LIST_PATHS.includes(routeKey(pathname));
}

export function isDetailRoute(pathname) {
  const key = routeKey(pathname);
  return DETAIL_PATTERNS.some((pattern) => pattern.test(key));
}

/**
 * Decide what to do with one request.
 *
 * @param {{url: string, method?: string, mode?: string, destination?: string}} request
 * @param {{appOrigin: string, apiOrigin?: string}} origins
 * @returns {string} one of STRATEGY
 */
export function strategyFor(request, origins) {
  const url = new URL(request.url);
  const method = request.method || "GET";

  // 1. Nothing that changes anything, ever. Checked before the origin test so that even a
  //    mutating request to somewhere unexpected cannot reach a caching branch.
  if (isMutating(method)) return STRATEGY.NETWORK_ONLY;

  const isAppOrigin = url.origin === origins.appOrigin;
  const isApiOrigin = Boolean(origins.apiOrigin) && url.origin === origins.apiOrigin;

  // 2. The cache is scoped to this application and its own API. A third-party origin is passed
  //    through to the network untouched and never enters storage.
  if (!isAppOrigin && !isApiOrigin) return STRATEGY.NETWORK_ONLY;

  // 3. Authentication, and the safety-critical actions named above.
  if (url.pathname.startsWith("/api/auth/")) return STRATEGY.NETWORK_ONLY;
  if (isNeverCached(url.pathname)) return STRATEGY.NETWORK_ONLY;

  // 4. Next.js's own data and flight requests: they are versioned with the render, and a stale
  //    one is worse than no cache at all.
  if (url.pathname.startsWith("/_next/data/") || url.searchParams.has("_rsc")) {
    return STRATEGY.NETWORK_ONLY;
  }

  if (isAppOrigin && isStaticAsset(url.pathname)) return STRATEGY.CACHE_FIRST;
  if (isListRoute(url.pathname)) return STRATEGY.STALE_WHILE_REVALIDATE;
  if (isDetailRoute(url.pathname)) return STRATEGY.NETWORK_FIRST;

  // 5. Any other page the user navigates to: worth a cached copy so a dropped connection leaves
  //    what is on screen readable, but never served ahead of the network.
  if (isAppOrigin && (request.mode === "navigate" || request.destination === "document")) {
    return STRATEGY.NETWORK_FIRST;
  }

  // 6. Everything else - signed downloads, job polling, anything a later  adds - goes to the
  //    network and is not stored. Caching by default is how a platform starts serving somebody
  //    a figure that is no longer true.
  return STRATEGY.NETWORK_ONLY;
}

/** Whether a cached entry stamped at `cachedAt` may still be served. */
export function isFresh(cachedAt, now, ttlSeconds = CACHE_TTL_SECONDS) {
  if (!cachedAt) return false;
  const stamped = new Date(cachedAt).getTime();
  if (Number.isNaN(stamped)) return false;
  const age = (now - stamped) / 1000;
  return age >= 0 && age <= ttlSeconds;
}

/** The cache names for one deployed build. A new build hash means a new, empty pair. */
export function cacheNames(version) {
  return {
    precache: `agfze-precache-${version}`,
    runtime: `agfze-runtime-${version}`,
  };
}

/** Every cache belonging to this application, current or not. Used to sweep old builds. */
export function isApplicationCache(name) {
  return typeof name === "string" && name.startsWith("agfze-");
}
