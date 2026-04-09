// @odoo-module ignore

const cacheName = "odoo-pos-cache";

// Take control immediately when the browser installs a new version of
// this file (byte-level diff triggers install).  Without this, the old
// service worker stays active until all POS tabs are closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
    // Claim clients immediately so the new fetch handler takes effect.
    // Do NOT purge the cache — it contains employee avatars and other
    // images that are expensive to re-fetch (58+ concurrent requests
    // exhausts the threaded server).  Stale JS/CSS is not an issue
    // because asset URLs include a content hash that changes on rebuild.
    event.waitUntil(self.clients.claim());
});

const fetchCacheRespond = async (event) => {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(event.request);
        cache.put(event.request, response.clone());
        return response;
    } catch {
        // Network failed — try cache. If both miss, fall back to a
        // synthetic 503 so respondWith() always gets a valid Response.
        return (await cache.match(event.request)) ||
            new Response("Service Unavailable", { status: 503, statusText: "Service Unavailable" });
    }
};

const cacheResources = async (event) => {
    const url = event.request.url;

    try {
        const cache = await caches.open(cacheName);
        await cache.add(url);
    } catch (error) {
        console.info("Failed to cache resource", url, error);
    }
};

self.addEventListener("fetch", (event) => {
    const url = event.request.url;

    // Only intercept requests that were explicitly pre-cached via the
    // urlsToCache message (asset bundles, fonts, etc.).  Everything else
    // — images, RPCs, ESM source files — goes directly to the browser's
    // fetch pipeline which has proper connection pooling (6 per origin).
    // Intercepting 100+ concurrent image/RPC requests from the SW
    // bypasses that pooling and exhausts the threaded server.
    if (
        url.includes("extension") ||
        url.includes("web/dataset") ||
        url.includes("hw_proxy/hello") ||
        url.includes("/static/src/") ||
        url.includes("/static/tests/") ||
        url.includes("/static/lib/") ||
        url.includes("/web/image") ||
        event.request.method !== "GET"
    ) {
        return;
    }

    event.respondWith(fetchCacheRespond(event));
});

// Handle notification
self.addEventListener("message", (event) => {
    const data = event.data;
    if (data.urlsToCache && navigator.onLine) {
        for (const url of data.urlsToCache) {
            cacheResources({ request: { url } });
        }
    }
});
