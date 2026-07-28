// @odoo-module ignore

const cacheName = "odoo-sw-cache";
const homepageURL = "/odoo";
const offLineURL = `${homepageURL}/offline`;

const staticCacheName = "odoo-static-cache";

const STATIC_PATH_RE = /^\/web\/assets\/(esm\/)?[0-9a-f]{7,}\//;
const IMAGE_PATH_RE = /^\/web\/image(\/|$)/;

/**
 * Whether a request URL may be served stale-while-revalidate from the
 * static cache.
 *
 * @param {URL} url
 * @returns {boolean}
 */
const isStaleWhileRevalidateURL = (url) =>
    STATIC_PATH_RE.test(url.pathname) ||
    (IMAGE_PATH_RE.test(url.pathname) && !!url.searchParams.get("unique"));

const sessionInfoURL = "/web/__sw_session_info__";

/** In-memory fast path over the persisted session info. */
let sessionInfo = null;

self.addEventListener("install", (event) => {
    event.waitUntil(
        Promise.all([
            fetch(homepageURL).then((res) =>
                res.ok && !res.redirected ? storeDataOnCache(homepageURL, res) : null,
            ),
            caches.open(cacheName).then((cache) => cache.add(offLineURL)),
        ]),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(purgeSupersededStaticEntries());
});

/**
 * Deletes all ``/web/image`` and content-hashed ``/web/assets`` entries from
 * the static cache — the entries that are either mutable (images) or
 * superseded after a deploy (old asset hashes).  Also drops the
 * ``/web/webclient/translations`` entries earlier service-worker versions
 * cached: this version no longer intercepts that route (IndexedDB owns
 * translation caching — see STATIC_PATH_RE), so those entries are dead
 * weight that would otherwise linger forever.
 *
 * @returns {Promise<void>}
 */
const purgeSupersededStaticEntries = async () => {
    try {
        const cache = await caches.open(staticCacheName);
        for (const request of await cache.keys()) {
            const { pathname } = new URL(request.url);
            if (
                IMAGE_PATH_RE.test(pathname) ||
                pathname.startsWith("/web/assets/") ||
                pathname.startsWith("/web/webclient/translations")
            ) {
                await cache.delete(request);
            }
        }
    } catch {
        // Storage unavailable — nothing to purge.
    }
};

/**
 * Extracts the session info JSON string from an HTML page body, using a
 * balanced-brace scan from the ``odoo.__session_info__ = `` marker.  (A
 * non-greedy ``({.*?});`` regex would truncate the capture at the first
 * ``};`` occurring INSIDE a JSON string value — e.g. a company name —
 * corrupting both the scrub and the later restore.)
 *
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
 * Persists the extracted session info (or clears it when ``info`` is null)
 * in ``caches`` so a fresh service-worker instance can restore the cached
 * app shell after this instance is terminated.
 *
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
    } catch {
        // Storage unavailable — the in-memory copy still serves this
        // instance's lifetime.
    }
};

/**
 * Returns the session info, falling back to the persisted copy when this
 * service-worker instance has none in memory (fresh instance after idle
 * termination).
 *
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
 * Reads the full body of a response as a string.
 *
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
    reader.releaseLock();
    return result;
};

/**
 * Stores a page response in the cache, scrubbing the session info.
 *
 * @param {string} url
 * @param {Response} response
 * @returns {Promise<void>}
 */
const storeDataOnCache = async (url, response) => {
    const htmlBody = await getTextFromResponse(response);
    const isOffline = url.endsWith(offLineURL);
    const extracted = extractSessionInfo(htmlBody);
    if (!isOffline && !extracted) {
        console.warn(
            "[sw] could not extract session info from the app shell; " +
                "not caching it (offline mode disabled for this page).",
        );
        await saveSessionInfo(null);
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
 * Splices the session info back into a scrubbed app-shell body.  Uses a
 * replacer FUNCTION (not a string) so that ``$``-sequences inside ``info``
 * (``$$``, ``$&``, ``$'``, `` $` ``, ``$n`` — reachable via user/company
 * free-text fields in ``__session_info__``) are inserted verbatim instead
 * of being interpreted by ``String.prototype.replaceAll`` as substitution
 * patterns, which would corrupt the restored JSON and white-screen the
 * offline shell.
 *
 * @param {string} htmlBody
 * @param {string} info
 * @returns {string}
 */
const restoreSessionInfo = (htmlBody, info) =>
    htmlBody.replaceAll("@@@session_info_secret@@@", () => info);

/**
 * Reads a cached response and restores the session info placeholder.
 *
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
 * Serve the event's request using stale-while-revalidate: if a cached entry
 * exists, return it immediately while kicking off a background fetch
 * to refresh the cache; otherwise go to the network.  Errors during the
 * background refresh are swallowed — the already-served cached response
 * is still valid, and the next request will retry.
 *
 * Only GET requests with 2xx responses are stored.  Opaque responses
 * and non-OK statuses are never cached.
 *
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
                await cache.put(request, response.clone()).catch(() => {
                    // Quota exceeded or storage disabled — drop silently.
                });
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
 * Fetches the request and falls back to cached or offline page on network failure.
 *
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

/**
 * Handles share_target POST requests by redirecting and forwarding the data.
 *
 * @param {FetchEvent} event
 * @returns {void}
 */
const serveShareTarget = (event) => {
    event.respondWith(Response.redirect("/odoo?share_target=trigger"));
    event.waitUntil(
        (async () => {
            await waitingMessage("odoo_share_target");
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

self.addEventListener("fetch", (event) => {
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
        (event.request.mode === "navigate" &&
            event.request.destination === "document") ||
        event.request.headers.get("accept")?.includes("text/html")
    ) {
        event.respondWith(navigateOrDisplayOfflinePage(event));
    }
});

/** @type {Map<string, Array<() => void>>} */
const nextMessageMap = new Map();

/**
 * Returns a promise resolved the next time the given message is received.
 *
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

self.addEventListener("message", (event) => {
    if (event.data?.type === "SKIP_WAITING") {
        self.skipWaiting();
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
        caches.delete(staticCacheName).catch(() => {
            // Storage unavailable (private mode, quota exceeded
            // during delete, ...) — nothing to do; entries are
            // harmless if they stay.
        });
    }
});

self.__ODOO_SW_TEST_HOOKS__ = {
    extractSessionInfo,
    isStaleWhileRevalidateURL,
    restoreSessionInfo,
};
