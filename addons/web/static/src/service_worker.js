// @odoo-module ignore

/**
 * @type {ServiceWorkerGlobalScope}
 */
const sw = /** @type {any} */ (self);

const CACHE_VERSION = "v1";
const CACHE_PREFIX = "odoo-sw-cache";
const STATIC_CACHE_PREFIX = "odoo-static-cache";

const cacheName = `${CACHE_PREFIX}-${CACHE_VERSION}`;
const homepageURL = "/odoo";
const offLineURL = `${homepageURL}/offline`;

const staticCacheName = `${STATIC_CACHE_PREFIX}-${CACHE_VERSION}`;

const STATIC_PATH_RE = /^\/web\/assets\/(esm\/)?[0-9a-f]{7,}\//;
const IMAGE_PATH_RE = /^\/web\/image(\/|$)/;

/**
 * @param {URL} url
 * @returns {boolean}
 */
const isStaleWhileRevalidateURL = (url) =>
    STATIC_PATH_RE.test(url.pathname) ||
    (IMAGE_PATH_RE.test(url.pathname) && !!url.searchParams.get("unique"));

const sessionInfoURL = "/web/__sw_session_info__";

/** @type {any} */
let sessionInfo = null;

sw.addEventListener("install", (event) => {
    event.waitUntil(
        Promise.all([
            fetch(homepageURL).then((res) =>
                res.ok && !res.redirected ? storeDataOnCache(homepageURL, res) : null,
            ),
            caches.open(cacheName).then((cache) => cache.add(offLineURL)),
        ]),
    );
});

sw.addEventListener("activate", (event) => {
    event.waitUntil(activateCaches());
});

/**
 * @returns {Promise<void>}
 */
const activateCaches = async () => {
    try {
        await migrateSupersededCaches();
        await collectSupersededAssets();
        await deleteSupersededCaches();
    } catch {}
};

/**
 * @param {string} name
 * @returns {boolean}
 */
const isOwnedCacheName = (name) =>
    name === CACHE_PREFIX ||
    name === STATIC_CACHE_PREFIX ||
    name.startsWith(`${CACHE_PREFIX}-`) ||
    name.startsWith(`${STATIC_CACHE_PREFIX}-`);

/**
 * @param {URL} url
 * @returns {boolean}
 */
const isShellURL = (url) =>
    [homepageURL, offLineURL, sessionInfoURL].includes(url.pathname);

/**
 * @param {string} fromName
 * @param {string} toName
 * @param {(url: URL) => boolean} shouldKeep
 * @returns {Promise<void>}
 */
const copyMissingEntries = async (fromName, toName, shouldKeep) => {
    const from = await caches.open(fromName);
    const to = await caches.open(toName);
    for (const request of await from.keys()) {
        if (!shouldKeep(new URL(request.url)) || (await to.match(request))) {
            continue;
        }
        const response = await from.match(request);
        if (response) {
            await to.put(request, response);
        }
    }
};

/**
 * @returns {Promise<void>}
 */
const migrateSupersededCaches = async () => {
    for (const name of await caches.keys()) {
        if (name === cacheName || name === staticCacheName) {
            continue;
        }
        if (name === CACHE_PREFIX) {
            await copyMissingEntries(name, cacheName, isShellURL);
        } else if (
            name === STATIC_CACHE_PREFIX ||
            name.startsWith(`${STATIC_CACHE_PREFIX}-`)
        ) {
            await copyMissingEntries(name, staticCacheName, isStaleWhileRevalidateURL);
        }
    }
};

const ASSET_RETENTION_MS = 30 * 24 * 60 * 60 * 1000;

const SHELL_ASSET_URL_RE = /\/web\/assets\/(?:esm\/)?[0-9a-f]{7,}\/[^"'\s<>]*/g;

/**
 * @returns {Promise<Set<string> | null>}
 */
const getShellReferencedAssetPaths = async () => {
    const cache = await caches.open(cacheName);
    const paths = new Set();
    let hasShell = false;
    for (const url of [homepageURL, offLineURL]) {
        const response = await cache.match(url);
        if (!response) {
            continue;
        }
        hasShell = true;
        const html = await getTextFromResponse(response);
        for (const match of html.match(SHELL_ASSET_URL_RE) ?? []) {
            paths.add(match);
        }
    }
    return hasShell ? paths : null;
};

/**
 * @returns {Promise<void>}
 */
const collectSupersededAssets = async () => {
    const referenced = await getShellReferencedAssetPaths();
    if (!referenced) {
        return;
    }
    const cache = await caches.open(staticCacheName);
    const now = Date.now();
    for (const request of await cache.keys()) {
        const { pathname } = new URL(request.url);
        if (!STATIC_PATH_RE.test(pathname) || referenced.has(pathname)) {
            continue;
        }
        const response = await cache.match(request);
        const fetchedAt = Date.parse(response?.headers.get("date") ?? "");
        if (!Number.isNaN(fetchedAt) && now - fetchedAt > ASSET_RETENTION_MS) {
            await cache.delete(request);
        }
    }
};

/**
 * @returns {Promise<void>}
 */
const deleteSupersededCaches = async () => {
    for (const name of await caches.keys()) {
        if (name !== cacheName && name !== staticCacheName && isOwnedCacheName(name)) {
            await caches.delete(name);
        }
    }
};

/**
 * @param {string} htmlContent
 * @returns {string | null}
 */
const extractSessionInfo = (htmlContent) => {
    const marker = htmlContent.match(/odoo\.__session_info__\s*=\s*/);
    if (!marker) {
        return null;
    }
    const start = marker.index + marker[0].length;
    if (htmlContent[start] !== "{") {
        return null;
    }
    let depth = 0;
    let inString = false;
    let escaped = false;
    for (let i = start; i < htmlContent.length; i++) {
        const ch = htmlContent[i];
        if (inString) {
            if (escaped) {
                escaped = false;
            } else if (ch === "\\") {
                escaped = true;
            } else if (ch === '"') {
                inString = false;
            }
        } else if (ch === '"') {
            inString = true;
        } else if (ch === "{") {
            depth++;
        } else if (ch === "}") {
            depth--;
            if (depth === 0) {
                return htmlContent.slice(start, i + 1);
            }
        }
    }
    return null;
};

/**
 * @param {string | null} info
 * @returns {Promise<void>}
 */
const saveSessionInfo = async (info) => {
    sessionInfo = info;
    try {
        const cache = await caches.open(cacheName);
        if (info) {
            await cache.put(
                sessionInfoURL,
                new Response(info, {
                    headers: { "Content-Type": "application/json" },
                }),
            );
        } else {
            await cache.delete(sessionInfoURL);
        }
    } catch {}
};

/**
 * @returns {Promise<string | null>}
 */
const getSessionInfo = async () => {
    if (sessionInfo) {
        return sessionInfo;
    }
    try {
        const cache = await caches.open(cacheName);
        const response = await cache.match(sessionInfoURL);
        sessionInfo = response ? await response.text() : null;
    } catch {
        sessionInfo = null;
    }
    return sessionInfo;
};

/**
 * @param {Response} response
 * @returns {Promise<string>}
 */
const getTextFromResponse = async (response) => {
    const reader = response.clone().body.getReader();
    const decoder = new TextDecoder();
    let result = "";
    while (true) {
        const { value, done } = await reader.read();
        if (done) {
            break;
        }
        result += decoder.decode(value, { stream: true });
    }
    result += decoder.decode();
    reader.releaseLock();
    return result;
};

/**
 * @param {string} url
 * @param {Response} response
 * @returns {Promise<void>}
 */
const storeDataOnCache = async (url, response) => {
    const htmlBody = await getTextFromResponse(response);
    const isOffline = url.endsWith(offLineURL);
    const extracted = extractSessionInfo(htmlBody);
    if (!isOffline && !extracted) {
        return;
    }
    await saveSessionInfo(extracted);
    const cache = await caches.open(cacheName);
    const body = extracted
        ? htmlBody.replace(extracted, "@@@session_info_secret@@@")
        : htmlBody;
    return cache.put(
        isOffline ? url : homepageURL,
        new Response(body, { headers: { "Content-Type": "text/html" } }),
    );
};

/**
 * @param {string} htmlBody
 * @param {string} info
 * @returns {string}
 */
const restoreSessionInfo = (htmlBody, info) =>
    htmlBody.replaceAll("@@@session_info_secret@@@", () => info);

/**
 * @param {string} url
 * @returns {Promise<Response | undefined>}
 */
const readDataOnCache = async (url) => {
    const cache = await caches.open(cacheName);
    const response = await cache.match(url);
    if (url === offLineURL) {
        return response;
    }
    if (!response) {
        if (url === homepageURL) {
            return undefined;
        }
        return readDataOnCache(homepageURL);
    }
    const htmlBody = await getTextFromResponse(response);
    const info = await getSessionInfo();
    if (!info) {
        return undefined;
    }
    return new Response(restoreSessionInfo(htmlBody, info), {
        headers: { "Content-Type": "text/html" },
    });
};

const fetchErrorMessages = [
    "Failed to fetch",
    "Load failed",
    "NetworkError when attempting to fetch resource.",
];

/**
 * @param {FetchEvent} event
 * @returns {Promise<Response>}
 */
const staleWhileRevalidate = async (event) => {
    const request = event.request;
    const cache = await caches.open(staticCacheName);
    const cached = await cache.match(request);
    const networkPromise = fetch(request)
        .then(async (response) => {
            if (response.ok) {
                await cache.put(request, response.clone()).catch(() => {});
            } else if (
                (response.status === 401 || response.status === 403) &&
                IMAGE_PATH_RE.test(new URL(request.url).pathname)
            ) {
                await cache.delete(request).catch(() => {});
            }
            return response;
        })
        .catch(() => cached);
    if (cached) {
        event.waitUntil(networkPromise);
        return cached;
    }
    return networkPromise;
};

/**
 * @param {FetchEvent} event
 * @returns {Promise<Response>}
 */
const navigateOrDisplayOfflinePage = async (event) => {
    const request = event.request;
    const isDebugAssets = new URL(request.url).searchParams
        .get("debug")
        ?.includes("assets");
    try {
        const response = await fetch(request);
        if (response.ok && !isDebugAssets) {
            event.waitUntil(storeDataOnCache(request.url, response.clone()));
        }
        return response;
    } catch (requestError) {
        if (
            request.method === "GET" &&
            requestError instanceof TypeError &&
            fetchErrorMessages.includes(requestError.message)
        ) {
            const info = await getSessionInfo();
            if (info?.length && !isDebugAssets) {
                const cachedResponse = await readDataOnCache(request.url);
                if (cachedResponse) {
                    return cachedResponse;
                }
            }
            const offlinePage = await readDataOnCache(offLineURL);
            if (offlinePage) {
                return offlinePage;
            }
        }
        throw requestError;
    }
};

const SHARE_TARGET_TIMEOUT_MS = 30000;

/**
 * @param {FetchEvent} event
 * @returns {void}
 */
const serveShareTarget = (event) => {
    event.respondWith(Response.redirect("/odoo?share_target=trigger"));
    event.waitUntil(
        (async () => {
            const messaged = await Promise.race([
                waitingMessage("odoo_share_target").then(() => true),
                new Promise((resolve) =>
                    setTimeout(() => resolve(false), SHARE_TARGET_TIMEOUT_MS),
                ),
            ]);
            if (!messaged) {
                return;
            }
            const client = await /** @type {any} */ (self).clients.get(
                event.resultingClientId || event.clientId,
            );
            if (!client) {
                return;
            }
            const data = await event.request.formData();
            client.postMessage({
                shared_files: data.getAll("externalMedia") || [],
                action: "odoo_share_target_ack",
            });
        })(),
    );
};

sw.addEventListener("fetch", (event) => {
    if (
        event.request.method === "POST" &&
        new URL(event.request.url).searchParams.has("share_target")
    ) {
        return serveShareTarget(event);
    }
    if (
        event.request.method === "GET" &&
        isStaleWhileRevalidateURL(new URL(event.request.url))
    ) {
        event.respondWith(staleWhileRevalidate(event));
        return;
    }
    if (
        event.request.method === "GET" &&
        event.request.mode === "navigate" &&
        (event.request.destination === "document" ||
            event.request.headers.get("accept")?.includes("text/html"))
    ) {
        event.respondWith(navigateOrDisplayOfflinePage(event));
    }
});

/** @type {Map<string, Array<() => void>>} */
const nextMessageMap = new Map();

/**
 * @param {string} message
 * @returns {Promise<void>}
 */
const waitingMessage = async (message) =>
    new Promise((resolve) => {
        if (!nextMessageMap.has(message)) {
            nextMessageMap.set(message, []);
        }
        nextMessageMap.get(message).push(resolve);
    });

sw.addEventListener("message", (event) => {
    if (event.data?.type === "SKIP_WAITING") {
        sw.skipWaiting();
        return;
    }
    const messageNotifiers = nextMessageMap.get(event.data);
    if (messageNotifiers) {
        for (const messageNotified of messageNotifiers) {
            messageNotified();
        }
        nextMessageMap.delete(event.data);
    }
    if (event.data === "user_logout") {
        saveSessionInfo(null);
        caches.delete(staticCacheName).catch(() => {});
    }
});

sw.__ODOO_SW_TEST_HOOKS__ = {
    extractSessionInfo,
    isStaleWhileRevalidateURL,
    restoreSessionInfo,
};
