// @odoo-module ignore
/// <reference lib="webworker" />

const cacheName = "odoo-sw-cache";
const homepageURL = "/odoo";
const offLineURL = `${homepageURL}/offline`;

// Separate cache for long-lived static responses.  Distinct from
// ``cacheName`` above so a ``caches.delete`` on logout purges user-scoped
// data without nuking the offline page.  Holds translations, asset
// bundles, and ``/web/image/`` responses — all content-addressable (the
// URL changes when the content changes), so stale-while-revalidate is
// safe.
const staticCacheName = "odoo-static-cache";

// URL patterns eligible for stale-while-revalidate: translation bundles,
// asset bundles, and /web/image/ responses. Matches path-only
// (``url.pathname``) to avoid query-string false positives. All three are
// keyed by a cache-busting hash/id in the URL, so reusing a cached entry
// for a matching URL is always correct.
const STALE_WHILE_REVALIDATE_RE =
    /^\/web\/(webclient\/translations|assets|image)(\/|$)/;

let sessionInfo = null;

self.addEventListener("install", (event) => {
    event.waitUntil(
        Promise.all([
            // Needed because the sw is register after the initial fetch
            fetch(homepageURL).then((res) =>
                res.ok ? storeDataOnCache(homepageURL, res) : null,
            ),
            caches.open(cacheName).then((cache) => cache.add(offLineURL)),
        ]),
    );
});

/**
 * Extracts the session info JSON string from an HTML page body.
 *
 * @param {string} htmlContent
 * @returns {string | null}
 */
const extractSessionInfo = (htmlContent) => {
    const match = htmlContent.match(/odoo\.__session_info__\s*=\s*({.*?});/s);
    return match && match[1] ? match[1] : null;
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
    // store on ram, the session info
    sessionInfo = extractSessionInfo(htmlBody);
    const cache = await caches.open(cacheName);
    const body = sessionInfo
        ? htmlBody.replace(sessionInfo, "@@@session_info_secret@@@")
        : htmlBody;
    return cache.put(
        url.endsWith(offLineURL) ? url : homepageURL,
        new Response(body, { headers: response.headers }),
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
    return new Response(htmlBody.replaceAll("@@@session_info_secret@@@", sessionInfo), {
        headers: response.headers,
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
 * @param {Request} request
 * @returns {Promise<Response>}
 */
const navigateOrDisplayOfflinePage = async (request) => {
    const isDebugAssets = new URL(request.url).searchParams
        .get("debug")
        ?.includes("assets");
    try {
        const response = await fetch(request);
        if (response.ok && !isDebugAssets) {
            storeDataOnCache(request.url, response.clone());
        }
        return response;
    } catch (requestError) {
        if (
            request.method === "GET" &&
            requestError instanceof TypeError &&
            fetchErrorMessages.includes(requestError.message)
        ) {
            if (sessionInfo?.length && !isDebugAssets) {
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
    if (event.request.method === "GET") {
        const pathname = new URL(event.request.url).pathname;
        if (STALE_WHILE_REVALIDATE_RE.test(pathname)) {
            event.respondWith(staleWhileRevalidate(event.request));
            return;
        }
    }
    if (
        (event.request.mode === "navigate" &&
            event.request.destination === "document") ||
        // request.mode = navigate isn't supported in all browsers => check for http header accept:text/html
        event.request.headers.get("accept")?.includes("text/html")
    ) {
        event.respondWith(navigateOrDisplayOfflinePage(event.request));
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
        sessionInfo = null;
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

// Service workers run as classic scripts (not ES modules).
// TypeScript scope isolation is handled by the /// <reference lib="webworker" /> directive above.
