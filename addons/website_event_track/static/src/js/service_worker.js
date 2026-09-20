/** @odoo-module native */

/* global idbKeyval */
/**
 * @type {ServiceWorkerGlobalScope}
 */
const sw = /** @type {any} */ (self);

importScripts("/website_event_track/static/lib/idb-keyval/idb-keyval.js");

const PREFIX = "odoo-event";
const SYNCABLE_ROUTES = ["/event/track/toggle_reminder"];
const CACHABLE_ROUTES = ["/web/webclient/version_info"];
const MAX_CACHE_SIZE = 512 * 1024 * 1024;
const MAX_CACHE_QUOTA = 0.5;
// eslint-disable-next-line no-undef
const CDN_URL = __ODOO_CDN_URL__;

const { Store, set, get } = idbKeyval;
const pendingRequestsQueueName = `${PREFIX}-pending-requests`;
const cacheName = `${PREFIX}-cache`;
const syncStore = new Store(`${PREFIX}-sync-db`, `${PREFIX}-sync-store`);
const cacheStore = new Store(`${PREFIX}-cache-db`, `${PREFIX}-cache-store`);
const offlineRoute = `${sw.registration.scope}/offline`;
const scopeURL = new URL(sw.registration.scope);
const cdnURL = CDN_URL
    ? CDN_URL.startsWith("http")
        ? new URL(CDN_URL)
        : new URL(`http:${CDN_URL}`)
    : undefined;

/**
 * @param {string} url
 * @returns {string}
 */
const urlPathname = (url) => new URL(url).pathname;

/**
 * @param {Array} whitelist
 * @returns {Function}
 */
const canHandleRoutes = (whitelist) => (url) => whitelist.includes(urlPathname(url));

/**
 * @param {Request} request
 * @returns {boolean}
 */
const isGET = (request) => request.method === "GET";

/**
 * @returns {Function}
 */
const isSyncableURL = canHandleRoutes(SYNCABLE_ROUTES);

/**
 * @returns {Function}
 */
const isCachableURL = canHandleRoutes(CACHABLE_ROUTES);

/**
 * @returns {boolean}
 */
const isCacheFull = async () => {
    if (!("storage" in navigator && "estimate" in navigator.storage)) {
        return false;
    }
    try {
        const { usage, quota } = await navigator.storage.estimate();
        return usage / quota > MAX_CACHE_QUOTA || usage > MAX_CACHE_SIZE;
    } catch (error) {
        console.error(`call to storage.estimate failed`, error);
        return false;
    }
};

/**
 * @return {Promise}
 */
const fetchToCacheOfflinePage = () =>
    caches.open(cacheName).then((cache) => cache.add(offlineRoute));

/**
 * @param {Request} req
 * @returns {Promise<Object>}
 */
const serializeRequest = async (req) => ({
    url: req.url,
    method: req.method,
    headers: Object.fromEntries(req.headers.entries()),
    body: await req.text(),
    mode: req.mode,
    credentials: req.credentials,
    cache: req.cache,
    redirect: req.redirect,
    referrer: req.referrer,
    integrity: req.integrity,
});

/**
 * @param {Object} requestData
 * @returns {Request}
 */
const deserializeRequest = (requestData) => {
    const { url } = requestData;
    delete requestData.url;
    return new Request(url, requestData);
};

/**
 * @param {Response} res
 * @returns {Promise<Object>}
 */
const serializeResponse = async (res) => ({
    body: await res.text(),
    status: res.status,
    statusText: res.statusText,
    headers: Object.fromEntries(res.headers.entries()),
});

/**
 * @param {Object} responseData
 * @returns {Response}
 */
const deserializeResponse = (responseData) => {
    const { body } = responseData;
    delete responseData.body;
    return new Response(body, responseData);
};

/**
 * @param {Object} serializedRequest
 * @returns {string}
 */
const buildCacheKey = ({ url, body: { method, params } }) =>
    JSON.stringify({
        url,
        method,
        params,
    });

/**
 * @returns {int}
 */
const uniqueRequestId = () => Math.floor(Math.random() * 1000 * 1000 * 1000);

/**
 * @returns {Response}
 */
const buildEmptyResponse = () =>
    new Response(JSON.stringify({ jsonrpc: "2.0", id: uniqueRequestId(), result: {} }));

/**
 * @param {Request} request
 * @param {Response} response
 * @returns {Promise}
 */
const cacheRequest = async (request, response) => {
    const url = new URL(request.url);
    if (
        url.hostname !== scopeURL.hostname &&
        (!cdnURL || url.hostname !== cdnURL.hostname)
    ) {
        console.error(
            `ignoring cache for ${request.url} => ${url.hostname}, local: ${scopeURL.hostname}, cdn: ${cdnURL ? cdnURL.hostname : cdnURL}`,
        );
        return;
    }

    if (!response || !response.ok || response.type !== "basic") {
        console.error(
            `ignoring cache for ${request.url} => ${response.type}, mode: ${request.mode}, cache: ${request.cache}`,
        );
        return;
    }

    if (await isCacheFull()) {
        console.log("Cache full, not caching!");
        return;
    }

    console.log(`grant cache for ${request.url} => ${response.type}, mode: ${request.mode}, cache: ${request.cache},
                    isGet: ${isGET(request)}, isCachable: ${isCachableURL(request.url)}`);
    if (isGET(request)) {
        const cache = await caches.open(cacheName);
        await cache.put(request, response.clone());
    } else if (isCachableURL(request.url)) {
        const serializedRequest = await serializeRequest(request);
        const serializedResponse = await serializeResponse(response.clone());
        await set(buildCacheKey(serializedRequest), serializedResponse, cacheStore);
    }
};

/**
 * @param {Request} request
 * @returns {boolean}
 */
const isCachableRequest = (request) => isGET(request) || isCachableURL(request.url);

/**
 * @param request
 * @param requestError
 * @return {boolean}
 */
const isOfflineDocumentRequest = (request, requestError) =>
    request &&
    requestError &&
    requestError.message === "Failed to fetch" &&
    ((isGET(request) &&
        request.mode === "navigate" &&
        request.destination === "document") ||
        (request.method === "GET" &&
            request.headers.get("accept").includes("text/html")));

/**
 * @param {Request} request
 * @returns {Promise<Response|null>}
 */
const matchCache = async (request) => {
    if (isGET(request)) {
        const cache = await caches.open(cacheName);
        const response = await cache.match(request.url);
        if (response) {
            return deserializeResponse(await serializeResponse(response.clone()));
        }
    }
    if (isCachableURL(request.url)) {
        const serializedRequest = await serializeRequest(request);
        const cachedResponse = await get(buildCacheKey(serializedRequest), cacheStore);
        if (cachedResponse) {
            return deserializeResponse(cachedResponse);
        }
    }
    return null;
};

/**
 * @param {Request} request
 * @param {object} [options]
 * @param {Boolean} [options.disableTracking]
 * @returns {Promise<Response>}
 */
const processFetchRequest = async (request, options) => {
    const requestCopy = request.clone();
    let response;
    try {
        if (options && options.disableTracking) {
            response = await fetch(request, { headers: { "X-Disable-Tracking": "1" } });
        } else {
            response = await fetch(request);
        }
        await cacheRequest(request, response);
    } catch (requestError) {
        if (isCachableRequest(requestCopy)) {
            try {
                response = await matchCache(requestCopy);
            } catch (err) {
                console.warn("An error occurs when reading the cache request", err);
            }
        } else if (isSyncableURL(requestCopy.url)) {
            const pendingRequests =
                (await get(pendingRequestsQueueName, syncStore)) || [];
            const serializedRequest = await serializeRequest(requestCopy);
            await set(
                pendingRequestsQueueName,
                [...pendingRequests, serializedRequest],
                syncStore,
            );
            if (sw.registration.sync) {
                await sw.registration.sync
                    .register(pendingRequestsQueueName)
                    .catch((err) => {
                        console.warn("Cannot use BackgroundSync", err);
                        throw requestError;
                    });
            }
            return buildEmptyResponse();
        } else {
            console.warn(
                `Offline ${requestCopy.method} request currently not supported`,
                requestCopy,
            );
        }

        if (!response) {
            if (isOfflineDocumentRequest(request, requestError)) {
                const cache = await caches.open(cacheName);
                return await cache.match(offlineRoute);
            }
            throw requestError;
        }
    }
    return response;
};

/**
 * @returns {Promise}
 */
const processPendingRequests = async () => {
    const pendingRequests = (await get(pendingRequestsQueueName, syncStore)) || [];
    if (!pendingRequests.length) {
        console.info("Nothing to sync!");
        return;
    }
    let pendingRequest;
    while ((pendingRequest = pendingRequests.shift())) {
        const request = deserializeRequest(pendingRequest);
        await fetch(request);
        await set(pendingRequestsQueueName, pendingRequests, syncStore);
    }
};

/**
 * @param {Array<string>} urls
 */
const prefetchUrls = async (urls = []) => {
    const cache = await caches.open(cacheName);
    const uniqUrls = new Set(urls);
    for (let url of uniqUrls) {
        if (await cache.match(url)) {
            continue;
        }
        try {
            await processFetchRequest(new Request(url), { disableTracking: true });
        } catch (error) {
            console.error(`fail to prefetch ${url} : ${error}`);
        }
    }
};

/**
 * @param {Object} data
 * @param {string} data.action
 * @param {*} data.*
 * @returns {Promise}
 */
const processMessage = (data) => {
    const { action } = data;
    switch (action) {
        case "prefetch-pages": {
            const { urls: pagesUrls } = data;
            const maybeRedirectedUrl = pagesUrls.map((url) =>
                url.endsWith("/") ? url.slice(0, -1) : url,
            );
            return prefetchUrls([...pagesUrls, ...maybeRedirectedUrl]);
        }
        case "prefetch-assets": {
            const { urls: assetsUrls } = data;
            return prefetchUrls(assetsUrls);
        }
    }
    throw new Error(`Action '${action}' not found.`);
};

sw.addEventListener("fetch", (event) => {
    event.respondWith(processFetchRequest(event.request));
});

sw.addEventListener("sync", (event) => {
    console.info(`Syncing pending requests...`);
    if (event.tag === pendingRequestsQueueName) {
        event.waitUntil(processPendingRequests());
    }
});

sw.addEventListener("message", (event) => {
    event.waitUntil(processMessage(event.data));
});

sw.addEventListener("install", (event) => {
    event.waitUntil(fetchToCacheOfflinePage());
});
