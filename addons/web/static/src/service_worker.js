// @odoo-module ignore
/// <reference lib="webworker" />

const cacheName = "odoo-sw-cache";
const homepageURL = "/odoo";
const offLineURL = `${homepageURL}/offline`;

// Separate cache for long-lived static responses.  Distinct from
// ``cacheName`` above so a ``caches.delete`` on logout purges user-scoped
// data without nuking the offline page.  Holds translations, asset
// bundles, and cache-busted ``/web/image/`` responses.
const staticCacheName = "odoo-static-cache";

// URL patterns eligible for stale-while-revalidate.  Only CONTENT-ADDRESSED
// asset URLs qualify: `/web/assets/<hex-hash>/…` (or `/web/assets/esm/<hash>/…`)
// — reusing a cached entry for such a URL is always correct because the hash
// changes when the content does.  The binary controller also serves MUTABLE
// asset URLs where the "unique" segment is `debug`, `any`, or `%`
// (controllers/binary.py); requiring a hex-hash segment (>=7 hex chars)
// excludes those, so a developer in `?debug=assets` no longer gets the
// previous build served stale on every reload.  Translations are versioned
// by the same hash round-trip and match their own route.
const STATIC_PATH_RE =
    /^\/web\/(webclient\/translations(\/|$)|assets\/(esm\/)?[0-9a-f]{7,}\/)/;
// ``/web/image/`` URLs are only content-addressable when the caller passed a
// cache-busting token (``unique=`` — see ``core/utils/urls.js:imageUrl``); a
// bare ``/web/image/<model>/<id>/<field>`` URL is mutable server-side and
// must NOT be served stale-first.
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

// Synthetic cache key holding the session info scrubbed out of the cached
// app shell.  Persisted in ``caches`` (module state does not survive the
// ~30s idle termination of a service worker instance; a fresh instance
// would otherwise never be able to serve the cached shell offline).
const sessionInfoURL = "/web/__sw_session_info__";

/** In-memory fast path over the persisted session info. */
let sessionInfo = null;

self.addEventListener("install", (event) => {
    event.waitUntil(
        Promise.all([
            // Needed because the sw is register after the initial fetch.
            // Skip redirected responses: an invalid/expired session answers
            // /odoo with a 303 to the login page, and caching that as the app
            // shell would serve the login screen offline forever.
            fetch(homepageURL).then((res) =>
                res.ok && !res.redirected ? storeDataOnCache(homepageURL, res) : null,
            ),
            caches.open(cacheName).then((cache) => cache.add(offLineURL)),
        ]),
    );
});

self.addEventListener("activate", (event) => {
    // "activate" fires exactly once per new service-worker version taking
    // over.  Image entries are only correct while the record they belong to
    // is — a version change is a cheap, reliable point to drop them.  Asset
    // entries are content-addressed (hash in the path), so after a deploy the
    // HTML references NEW hashes and the old cached bundles are dead weight
    // that only ever grows: purge them here too, bounding the static cache to
    // roughly one deploy's worth instead of accumulating every superseded
    // bundle set until browser quota eviction nukes the whole origin (which
    // would also take the IndexedDB RPC cache with it).  Translations stay
    // (small, re-validated by the hash round-trip).
    event.waitUntil(purgeSupersededStaticEntries());
});

/**
 * Deletes all ``/web/image`` and content-hashed ``/web/assets`` entries from
 * the static cache — the entries that are either mutable (images) or
 * superseded after a deploy (old asset hashes).
 *
 * @returns {Promise<void>}
 */
const purgeSupersededStaticEntries = async () => {
    try {
        const cache = await caches.open(staticCacheName);
        for (const request of await cache.keys()) {
            const { pathname } = new URL(request.url);
            if (IMAGE_PATH_RE.test(pathname) || pathname.startsWith("/web/assets/")) {
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
    // JSON string literals only use double quotes; track them (and escapes)
    // so braces inside string values don't unbalance the scan.
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
    // Fail CLOSED on the scrub: if extraction fails (the marker regex is
    // format-coupled to `odoo.__session_info__ = {`; a template/serializer
    // change breaks it silently), the page still carries the session info +
    // registry HMAC + company data. Caching it would persist that at rest in
    // Cache Storage indefinitely. The offline shell (no session info) is
    // exempt — nothing to scrub there.
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
        // Minimal headers: the scrub changes the body length, so reusing the
        // network response's Content-Length / Content-Encoding would describe
        // a body that no longer matches (and a stale Content-Encoding could
        // make the browser try to gunzip plain text).
        new Response(body, { headers: { "Content-Type": "text/html" } }),
    );
};

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
    // if you come from /odoo to project the url is now /odoo/project, but it doesn't exist in cache so use /odoo instead
    if (!response) {
        if (url === homepageURL) {
            return undefined; // homepage itself is not cached — nothing to serve
        }
        return readDataOnCache(homepageURL);
    }
    const htmlBody = await getTextFromResponse(response);
    const info = await getSessionInfo();
    if (!info) {
        // No session info to splice back in: the scrubbed shell would boot
        // with a corrupt placeholder — treat as uncacheable.
        return undefined;
    }
    return new Response(htmlBody.replaceAll("@@@session_info_secret@@@", info), {
        // Minimal headers: the restored body differs in length from what the
        // original network headers describe (see storeDataOnCache).
        headers: { "Content-Type": "text/html" },
    });
};

const fetchErrorMessages = [
    "Failed to fetch", // Chromium
    "Load failed", // WebKit
    "NetworkError when attempting to fetch resource.", // Firefox
];

/**
 * Serve ``request`` using stale-while-revalidate: if a cached entry
 * exists, return it immediately while kicking off a background fetch
 * to refresh the cache; otherwise go to the network.  Errors during the
 * background refresh are swallowed — the already-served cached response
 * is still valid, and the next request will retry.
 *
 * Only GET requests with 2xx responses are stored.  Opaque responses
 * and non-OK statuses are never cached.
 *
 * @param {Request} request
 * @returns {Promise<Response>}
 */
const staleWhileRevalidate = async (request) => {
    const cache = await caches.open(staticCacheName);
    const cached = await cache.match(request);
    const networkPromise = fetch(request)
        .then((response) => {
            if (response.ok) {
                // ``response.clone()`` because putting the original would
                // lock the body stream before we return it to the caller.
                cache.put(request, response.clone()).catch(() => {
                    // Quota exceeded or storage disabled — drop silently.
                });
            }
            return response;
        })
        .catch(() => cached);
    return cached || networkPromise;
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
            // Keep the worker alive until the shell is fully written: a
            // fire-and-forget storeDataOnCache could be cut off by the ~30s
            // idle termination mid-write, leaving a truncated/absent shell.
            event.waitUntil(storeDataOnCache(request.url, response.clone()));
        }
        return response;
    } catch (requestError) {
        if (
            request.method === "GET" &&
            requestError instanceof TypeError &&
            fetchErrorMessages.includes(requestError.message)
        ) {
            // getSessionInfo falls back to the persisted copy, so a fresh
            // service-worker instance (idle termination re-evaluates the
            // script) can still serve the cached app shell offline.
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
    // Redirect so the user can refresh the page without resending data.
    event.respondWith(Response.redirect("/odoo?share_target=trigger"));
    event.waitUntil(
        (async () => {
            // The page sends this message to tell the service worker it's ready to receive the file.
            await waitingMessage("odoo_share_target");
            const client = await /** @type {any} */ (self).clients.get(
                event.resultingClientId || event.clientId,
            );
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
    // Stale-while-revalidate for static, content-addressable resources.
    // Fires before the navigation branch because the URL patterns here
    // never match ``destination === "document"`` or ``accept: text/html``.
    if (
        event.request.method === "GET" &&
        isStaleWhileRevalidateURL(new URL(event.request.url))
    ) {
        event.respondWith(staleWhileRevalidate(event.request));
        return;
    }
    if (
        (event.request.mode === "navigate" &&
            event.request.destination === "document") ||
        // request.mode = navigate isn't supported in all browsers => check for http header accept:text/html
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
    const messageNotifiers = nextMessageMap.get(event.data);
    if (messageNotifiers) {
        for (const messageNotified of messageNotifiers) {
            messageNotified();
        }
        nextMessageMap.delete(event.data);
    }
    if (event.data === "user_logout") {
        // Clears both the in-memory copy and the persisted cache entry.
        saveSessionInfo(null);
        // Drop the static cache too — a different user might land on
        // this browser and any lingering hash-keyed responses that
        // depended on the prior user's ACLs (``/web/image/`` with a
        // non-public record) would be wrong.  The cache will rebuild
        // on first access after the next login.
        caches.delete(staticCacheName).catch(() => {
            // Storage unavailable (private mode, quota exceeded
            // during delete, ...) — nothing to do; entries are
            // harmless if they stay.
        });
    }
});

// Pure helpers exposed for unit testing.  Service workers run as classic
// scripts (no ``export``), so the hoot suite fetches this file's source,
// evaluates it against a stub ``self``, and reads the functions back from
// this hook object (see static/tests/core/service_worker.test.js).
// Harmless in production: it only adds a property to the worker global.
self.__ODOO_SW_TEST_HOOKS__ = {
    extractSessionInfo,
    isStaleWhileRevalidateURL,
};

// Service workers run as classic scripts (not ES modules).
// TypeScript scope isolation is handled by the /// <reference lib="webworker" /> directive above.
