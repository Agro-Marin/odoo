// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/urls - URL construction, origin resolution, image URL generation, and redirect handling */

import { browser } from "@web/core/browser/browser";
import { DateTime } from "@web/core/l10n/luxon";
import { session } from "@web/session";

class RedirectionError extends Error {}

/**
 * Transforms a key value mapping to a string formatted as url hash, e.g.
 * {a: "x", b: 2} -> "a=x&b=2"
 *
 * @param {Object} obj
 * @returns {string}
 */
export function objectToUrlEncodedString(obj) {
    return Object.entries(obj)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v ?? "")}`)
        .join("&");
}

/**
 * Gets the origin url of the page, or cleans a given one
 *
 * @param {string} [origin] a given origin url
 * @returns {string} a cleaned origin url
 */
export function getOrigin(origin) {
    if (origin) {
        // remove trailing slashes
        origin = origin.replace(/\/+$/, "");
    } else {
        const { host, protocol } = browser.location;
        origin = `${protocol}//${host}`;
    }
    return origin;
}

/**
 * @param {string} route the relative route, or absolute in the case of cors urls
 * @param {object} [queryParams] parameters to be appended as the url's queryString
 * @param {object} [options]
 * @param {string} [options.origin] a precomputed origin
 * @returns {string}
 */
export function url(route, queryParams, options = {}) {
    const origin = getOrigin(options.origin ?? session.origin);
    if (!route) {
        return origin;
    }

    let queryString = objectToUrlEncodedString(queryParams || {});
    queryString = queryString.length ? `?${queryString}` : queryString;

    // Compare the wanted url against the current origin
    const isAbsolute = ["http://", "https://", "//"].some((el) => route.startsWith(el));
    const prefix = isAbsolute ? "" : origin;
    return `${prefix}${route}${queryString}`;
}

/**
 * @param {string} model
 * @param {number} id
 * @param {string} field
 * @param {Object} [options]
 * @param {string} [options.access_token]
 * @param {string} [options.crop]
 * @param {string} [options.filename]
 * @param {number} [options.height]
 * @param {string|any} [options.unique]
 * @param {number} [options.width]
 * @returns {string}
 */
export function imageUrl(
    model,
    id,
    field,
    { access_token, crop, filename, height, unique, width } = {},
) {
    let route = `/web/image/${model}/${id}/${field}`;
    if (width && height) {
        route = `${route}/${width}x${height}`;
    }
    if (filename) {
        route = `${route}/${filename}`;
    }
    /** @type {{[key: string]: any}} */
    const urlParams = {};
    if (access_token) {
        urlParams.access_token = access_token;
    }
    if (crop) {
        urlParams.crop = crop;
    }
    if (unique) {
        if (DateTime && unique instanceof DateTime) {
            // `.ts` is luxon's internal epoch-ms, not in @types/luxon's public surface.
            urlParams.unique = /** @type {any} */ (unique).ts;
        } else if (DateTime && typeof unique === "string") {
            // Only a string can be parsed as an SQL datetime; DateTime.fromSQL
            // throws on any non-string input, so it must be guarded.
            const dateTimeFromUnique = DateTime.fromSQL(unique);
            if (dateTimeFromUnique.isValid) {
                urlParams.unique = /** @type {any} */ (dateTimeFromUnique).ts;
            } else if (unique.length) {
                urlParams.unique = unique;
            }
        } else if (typeof unique === "string") {
            if (unique.length) {
                urlParams.unique = unique;
            }
        } else {
            // Truthy but neither a DateTime nor a string (e.g. a numeric
            // timestamp): use it directly as a cache-busting token.
            urlParams.unique = unique;
        }
    }
    return url(route, urlParams);
}

/**
 * Gets dataURL (base64 data) from the given file or blob.
 * Technically wraps FileReader.readAsDataURL in Promise.
 *
 * @param {Blob | File} file
 * @returns {Promise<string>} resolved with the dataURL, or rejected if the file is
 *  empty or if an error occurs.
 */
export function getDataURLFromFile(file) {
    if (!file) {
        return Promise.reject(new Error("No file provided"));
    }
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener("load", () => {
            // Handle Chrome bug that creates invalid data URLs for empty files
            if (reader.result === "data:") {
                resolve(`data:${file.type};base64,`);
            } else {
                resolve(/** @type {string} */ (reader.result));
            }
        });
        // Reject with a real Error, not the raw ProgressEvent (which stringifies
        // to "[object ProgressEvent]" and carries no message).
        reader.addEventListener("abort", () =>
            reject(new Error("File reading was aborted")),
        );
        reader.addEventListener("error", () =>
            reject(new Error(reader.error?.message ?? "File reading failed")),
        );
        reader.readAsDataURL(file);
    });
}

/**
 * Schemes accepted as a hyperlink / navigation target. Anything else
 * (``javascript:``, ``data:``, ``vbscript:``, ``file:``, ...) can execute
 * script or exfiltrate and must be rejected.
 */
export const SAFE_URL_SCHEMES = ["http", "https", "ftp", "ftps", "mailto", "tel"];

/**
 * Returns whether ``href`` is safe to use as a hyperlink or navigation target.
 * A value carrying an explicit scheme is allowed only when that scheme is in
 * {@link SAFE_URL_SCHEMES}; a protocol-relative ``//host`` is rejected (open
 * redirect / mixed content); scheme-less values (relative paths, queries,
 * fragments) are allowed. Leading whitespace is ignored so e.g. " javascript:"
 * cannot slip through, and embedded ASCII tab/newlines (which the WHATWG URL
 * parser strips before resolving) can't be used to obfuscate a scheme, so e.g.
 * "java\tscript:" cannot slip through either.
 *
 * @param {string} href
 * @returns {boolean}
 */
export function isSafeUrlScheme(href) {
    if (typeof href !== "string") {
        return false;
    }
    // Normalize `href` to the SAME string the WHATWG URL/HTML parser will
    // resolve: it removes ASCII tab/newline (U+0009/A/D) from ANYWHERE, and
    // strips leading C0 controls (U+0000-U+001F) and space. Skipping this
    // lets a scheme hide from the checks below yet still execute on
    // navigation -- via an interior tab ("java<TAB>script:") or a leading
    // control before "javascript:" / "//evil". Strip leading controls by
    // code point, not a control-char regex (which trips `no-control-regex`).
    let cleaned = href.replace(/[\t\n\r]/g, "");
    let start = 0;
    while (start < cleaned.length && cleaned.charCodeAt(start) <= 0x20) {
        start++;
    }
    cleaned = cleaned.slice(start);
    if (/^\/\//.test(cleaned)) {
        return false;
    }
    const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(cleaned);
    if (scheme) {
        return SAFE_URL_SCHEMES.includes(scheme[1].toLowerCase());
    }
    return true;
}

/**
 * Safely redirects to the given url within the same origin.
 *
 * @param {string} url
 * @returns {void}
 * @throws {RedirectionError} if the given url has a different origin
 */
export function redirect(url) {
    const { origin, pathname } = browser.location;
    const _url = new URL(url, `${origin}${pathname}`);
    if (_url.origin !== origin) {
        throw new RedirectionError("Can't redirect to another origin");
    }
    browser.location.assign(_url.href);
}

/**
 * This function compares two URLs. It doesn't care about the order of the search parameters.
 *
 * @param {string} _url1
 * @param {string} _url2
 * @returns {boolean} true if the urls are identical, false otherwise
 */
export function compareUrls(_url1, _url2) {
    const url1 = new URL(_url1);
    const url2 = new URL(_url2);
    // Sort search params to compare order-independently. Using the serialized
    // sorted string preserves duplicate keys (e.g. ?a=1&a=2) which would be
    // collapsed by Object.fromEntries.
    url1.searchParams.sort();
    url2.searchParams.sort();
    return (
        url1.origin === url2.origin &&
        url1.pathname === url2.pathname &&
        url1.searchParams.toString() === url2.searchParams.toString() &&
        url1.hash === url2.hash
    );
}
