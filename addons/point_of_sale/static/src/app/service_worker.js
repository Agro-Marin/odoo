// @odoo-module ignore

const cacheName = "odoo-pos-cache";

const fetchCacheRespond = async (event) => {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(event.request);
        // Only cache successful responses: a transient 500/redirect-to-login
        // used to overwrite the good cached copy, so the next offline boot
        // served the error page instead of the bundle. waitUntil keeps the
        // worker alive until the write lands (and swallows its rejection).
        if (response.ok) {
            event.waitUntil?.(
                cache.put(event.request, response.clone()).catch(() => {}),
            );
        }
        return response;
    } catch {
        return await cache.match(event.request);
    }
};

const cacheResources = async (event) => {
    const url = event.request.url;

    try {
        const cache = await caches.open(cacheName);
        await cache.add(url);
    } catch (error) {
        console.warn("Failed to cache resource", url, error);
    }
};

self.addEventListener("fetch", (event) => {
    const url = event.request.url;

    // Ignore Chrome extensions and dataset. Dataset will be cached in indexedDB.
    if (
        url.includes("extension") ||
        url.includes("web/dataset") ||
        url.includes("hw_proxy/hello") ||
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
