// @odoo-module ignore

/**
 * @type {ServiceWorkerGlobalScope}
 */
const sw = /** @type {any} */ (self);

const cacheName = "odoo-pos-cache";

const fetchCacheRespond = async (event) => {
    const cache = await caches.open(cacheName);
    try {
        const response = await fetch(event.request);
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

sw.addEventListener("fetch", (event) => {
    const url = event.request.url;

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

sw.addEventListener("message", (event) => {
    const data = event.data;
    if (data.urlsToCache && navigator.onLine) {
        for (const url of data.urlsToCache) {
            cacheResources({ request: { url } });
        }
    }
});
