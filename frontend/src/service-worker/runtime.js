/**
 * The service worker itself: install, activate, fetch, push, notificationclick, message.
 *
 * Every routing decision is delegated to `strategy.js`, which the build script inlines above this
 * file. Nothing here re-decides what to cache; this file only carries out what was decided.
 *
 * Two rules govern the whole of it:
 *
 *   1. A mutating request is passed to the network and nothing else happens to it. It is not
 *      cached, not read from cache, and - most importantly - never queued for later replay. This
 *      platform's offline support is read-only, by design and permanently. A background-sync
 *      queue would mean an approval decision leaving somebody's pocket hours after they made it,
 *      against a record that has since moved on.
 *   2. Nothing this file stores is keyed by a Request object. Every `cache.put` is given a URL
 *      string, which means no request header - and so no `Authorization` header and no token -
 *      can end up in storage even by accident.
 *
 * `CACHE_VERSION` and `PRECACHE_MANIFEST` are injected by scripts/build-sw.mjs.
 */

const { precache: PRECACHE, runtime: RUNTIME } = cacheNames(CACHE_VERSION);

const APP_ORIGIN = self.location.origin;
const ORIGINS = { appOrigin: APP_ORIGIN, apiOrigin: API_ORIGIN };

const OFFLINE_URL = "/offline";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(PRECACHE);
      // Added one at a time rather than through addAll, so one asset that 404s on a particular
      // deployment cannot fail the whole install and leave the app with no offline page at all.
      await Promise.all(
        PRECACHE_MANIFEST.map(async (url) => {
          try {
            const response = await fetch(url, { cache: "reload", credentials: "same-origin" });
            if (response.ok) await cache.put(url, response);
          } catch {
            /* an asset that cannot be fetched at install time is fetched at runtime instead */
          }
        }),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // The caches are keyed to the deployed build hash, so a release invalidates every stale
      // response by name rather than by anybody remembering to clear a cache.
      const names = await caches.keys();
      await Promise.all(
        names
          .filter((name) => isApplicationCache(name) && name !== PRECACHE && name !== RUNTIME)
          .map((name) => caches.delete(name)),
      );
      await self.clients.claim();
    })(),
  );
});

function stamp(response) {
  // A copy carrying the moment it was stored, so the page can say "cached at 09:14" honestly
  // rather than presenting stale figures as live ones.
  const headers = new Headers(response.headers);
  headers.set(CACHED_AT_HEADER, new Date().toISOString());
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function readFromCache(url) {
  const cached = (await caches.match(url, { cacheName: RUNTIME })) || (await caches.match(url, { cacheName: PRECACHE }));
  if (!cached) return null;
  const cachedAt = cached.headers.get(CACHED_AT_HEADER);
  if (cached.headers.has(CACHED_AT_HEADER) && !isFresh(cachedAt, Date.now())) {
    // Past its fifteen minutes. Dropped rather than served: an expired entry is not a fallback,
    // it is a figure that stopped being true.
    const cache = await caches.open(RUNTIME);
    await cache.delete(url);
    return null;
  }
  return cached;
}

async function writeToCache(url, response) {
  if (!response || !response.ok) return;
  const cache = await caches.open(RUNTIME);
  // Keyed by URL string, never by the Request: no header of the original request is stored.
  await cache.put(url, stamp(response.clone()));
}

async function cacheFirst(request) {
  const url = request.url;
  const cached = await caches.match(url, { cacheName: PRECACHE });
  if (cached) return cached;
  const runtimeCached = await caches.match(url, { cacheName: RUNTIME });
  if (runtimeCached) return runtimeCached;
  const response = await fetch(request);
  await writeToCache(url, response);
  return response;
}

async function staleWhileRevalidate(request) {
  const url = request.url;
  const cached = await readFromCache(url);
  const network = fetch(request)
    .then(async (response) => {
      await writeToCache(url, response);
      return response;
    })
    .catch(() => null);

  if (cached) {
    // Refresh in the background; the reader gets the stale copy now, stamped so the banner can
    // say how old it is.
    return cached;
  }
  const response = await network;
  return response || offlineFallback(request);
}

async function networkFirst(request) {
  const url = request.url;
  try {
    const response = await fetch(request);
    await writeToCache(url, response);
    return response;
  } catch {
    // Only a genuine network failure reaches here. A 404 or a 500 is the server telling the
    // truth about the record and is returned untouched above.
    const cached = await readFromCache(url);
    return cached || offlineFallback(request);
  }
}

async function offlineFallback(request) {
  if (request.mode === "navigate" || request.destination === "document") {
    const offline = await caches.match(OFFLINE_URL, { cacheName: PRECACHE });
    if (offline) return offline;
  }
  return new Response(
    JSON.stringify({
      success: false,
      data: null,
      message: "You are offline and this has not been opened on this device before.",
      errors: [{ code: "offline", message: "No connection, and nothing cached for this request." }],
    }),
    { status: 503, headers: { "Content-Type": "application/json" } },
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const strategy = strategyFor(request, ORIGINS);

  // Network-only is a genuine no-op: the request is not intercepted at all, so nothing about it
  // - not the request, not the response - can pass through cache storage.
  if (strategy === STRATEGY.NETWORK_ONLY) return;

  if (strategy === STRATEGY.CACHE_FIRST) {
    event.respondWith(cacheFirst(request));
    return;
  }
  if (strategy === STRATEGY.STALE_WHILE_REVALIDATE) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }
  event.respondWith(networkFirst(request));
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = payload.title || "AGFZE Command Centre";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || "Something needs your attention.",
      icon: payload.icon || "/icons/icon-192.png",
      badge: payload.badge || "/icons/badge-72.png",
      // One notification per event, not a stack of identical ones, when several arrive at once.
      tag: payload.type || "agfze",
      renotify: true,
      data: { url: payload.url || "/notifications" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/notifications";
  event.waitUntil(
    (async () => {
      const clientList = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of clientList) {
        if (new URL(client.url).origin === APP_ORIGIN && "focus" in client) {
          await client.focus();
          if ("navigate" in client) await client.navigate(target);
          return;
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "CLEAR_CACHES") {
    // Sign-out. Every cached screen on this device can name a counterparty and quote a price, so
    // all of it goes - and the worker unregisters itself so nothing is left holding the old
    // build's storage on a shared machine.
    event.waitUntil(
      (async () => {
        const names = await caches.keys();
        await Promise.all(names.filter(isApplicationCache).map((name) => caches.delete(name)));
        if (event.ports && event.ports[0]) event.ports[0].postMessage({ cleared: true });
      })(),
    );
  }
});
