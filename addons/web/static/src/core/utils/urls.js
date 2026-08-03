// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/urls */

import { browser } from "@web/core/browser/browser";
import { DateTime } from "@web/core/l10n/luxon";
import { session } from "@web/session";

class RedirectionError extends Error {}

/**
 * @param {Object} obj
 * @returns {string}
 */
export function objectToUrlEncodedString(obj) {
    return Object.entries(obj)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v ?? "")}`)
        .join("&");
}

/**
 * @param {string} [origin]
 * @returns {string}
 */
export function getOrigin(origin) {
    if (origin) {
        origin = origin.replace(/\/+$/, "");
    } else {
        const { host, protocol } = browser.location;
        origin = `${protocol}//${host}`;
    }
    return origin;
}

/**
 * @param {string} route
 * @param {object} [queryParams]
 * @param {object} [options]
 * @param {string} [options.origin]
 * @returns {string}
 */
export function url(route, queryParams, options = {}) {
    const origin = getOrigin(options.origin ?? session.origin);
    if (!route) {
        return origin;
    }

    let queryString = objectToUrlEncodedString(queryParams || {});
    queryString = queryString.length ? `?${queryString}` : queryString;

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
        if (unique instanceof DateTime) {
            urlParams.unique = /** @type {any} */ (unique).ts;
        } else if (typeof unique === "string") {
            const dateTimeFromUnique = DateTime.fromSQL(unique);
            if (dateTimeFromUnique.isValid) {
                urlParams.unique = /** @type {any} */ (dateTimeFromUnique).ts;
            } else if (unique.length) {
                urlParams.unique = unique;
            }
        } else {
            urlParams.unique = unique;
        }
    }
    return url(route, urlParams);
}

/**
 * @param {Blob | File} file
 * @returns {Promise<string>}
 */
export function getDataURLFromFile(file) {
    if (!file) {
        return Promise.reject(new Error("No file provided"));
    }
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener("load", () => {
            if (reader.result === "data:") {
                resolve(`data:${file.type};base64,`);
            } else {
                resolve(/** @type {string} */ (reader.result));
            }
        });
        reader.addEventListener("abort", () =>
            reject(new Error("File reading was aborted")),
        );
        reader.addEventListener("error", () =>
            reject(new Error(reader.error?.message ?? "File reading failed")),
        );
        reader.readAsDataURL(file);
    });
}

const SAFE_URL_SCHEMES = ["http", "https", "ftp", "ftps", "mailto", "tel"];

/**
 * The default list governs urls that arrive as DATA — a record's url field, a
 * link in a server-sent notification. `extraSchemes` is for the callers that
 * also dispatch urls the app built itself, where a scheme meaningless as data
 * is meaningful as a target: `blob:` can only name an object this document
 * created, so it is inert in a record but real in an `ir.actions.act_url`.
 *
 * @param {string} href
 * @param {string[]} [extraSchemes] lowercase, without the colon
 * @returns {boolean}
 */
export function isSafeUrlScheme(href, extraSchemes = []) {
    if (typeof href !== "string") {
        return false;
    }
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
        const name = scheme[1].toLowerCase();
        return SAFE_URL_SCHEMES.includes(name) || extraSchemes.includes(name);
    }
    return true;
}

/**
 * @param {string} url
 * @returns {void}
 * @throws {RedirectionError}
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
 * @param {string} _url1
 * @param {string} _url2
 * @returns {boolean}
 */
export function compareUrls(_url1, _url2) {
    const url1 = new URL(_url1);
    const url2 = new URL(_url2);
    url1.searchParams.sort();
    url2.searchParams.sort();
    return (
        url1.origin === url2.origin &&
        url1.pathname === url2.pathname &&
        url1.searchParams.toString() === url2.searchParams.toString() &&
        url1.hash === url2.hash
    );
}
