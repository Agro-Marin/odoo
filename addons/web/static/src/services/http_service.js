// @ts-check
/** @odoo-module native */

/** @module @web/services/http_service - Simple HTTP GET/POST helpers with status checking and FormData support */

import { browser } from "@web/core/browser/browser";
import {
    ConnectionLostError,
    InvalidResponseError,
    NetworkError,
    RequestEntityTooLargeError,
} from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Throw a classified error (rpc.js hierarchy, so callers and error handlers
 * can branch on it) for non-ok statuses instead of falling through to an
 * opaque body-parse failure on HTML error pages.
 *
 * A 2xx response with an HTML content-type is classified too, in two cases:
 * ``fetch`` follows redirects, so a session-expired request lands on the HTML
 * login page with a 200.
 * - ``readMethod === "json"``: ``response.json()`` would otherwise die on the
 *   login page with a raw ``SyntaxError`` (ClientErrorDialog).
 * - ``rejectHtml`` opt-in: for non-JSON callers that must NOT swallow the login
 *   page as legitimate content — file downloads (``core/utils/files.js`` reads
 *   ``"text"``) and the PWA manifest fetch would otherwise hand the login-page
 *   HTML back as the file/manifest body with no re-auth prompt. It is opt-in so
 *   the deliberate "an explicit non-json readMethod still reads HTML bodies"
 *   contract (see ``http_service.test.js``) is preserved for other callers.
 * ``InvalidResponseError`` matches rpc.js's handling of the same response, so
 * the connection-lost handler routes it to the session-expired flow instead.
 *
 * @param {Response} response
 * @param {string} [readMethod] the body-read method the caller will use
 * @param {{ rejectHtml?: boolean }} [options]
 */
function checkResponseStatus(response, readMethod, { rejectHtml = false } = {}) {
    if (response.ok) {
        if (readMethod === "json" || rejectHtml) {
            const contentType = response.headers.get("content-type") || "";
            if (/text\/html/i.test(contentType)) {
                throw new InvalidResponseError(response.url, response.status);
            }
        }
        return;
    }
    const { status, url } = response;
    if (status >= 502 && status <= 504) {
        // 502 Bad Gateway / 503 Service Unavailable / 504 Gateway Timeout
        const error = new ConnectionLostError(url);
        error.message += ` (HTTP ${status})`;
        throw error;
    }
    if (status === 413) {
        const error = new RequestEntityTooLargeError();
        error.message += ` (HTTP 413 at "${url}")`;
        throw error;
    }
    throw new NetworkError(`HTTP ${status} response at "${url}"`);
}

/**
 * @param {string} route
 * @param {string} [readMethod="json"]
 * @param {{ rejectHtml?: boolean }} [options] ``rejectHtml``: throw
 *   ``InvalidResponseError`` (→ session-expired flow) on a 2xx HTML body, for
 *   non-JSON callers that must not accept the login page as content.
 * @returns {Promise<any>}
 */
export async function get(route, readMethod = "json", options = {}) {
    const response = await browser.fetch(route, { method: "GET" });
    checkResponseStatus(response, readMethod, options);
    return /** @type {any} */ (response)[readMethod]();
}

/**
 * @param {string} route
 * @param {Record<string, any> | FormData} [params={}]
 * @param {string} [readMethod="json"]
 * @param {{ rejectHtml?: boolean }} [options] ``rejectHtml``: throw
 *   ``InvalidResponseError`` (→ session-expired flow) on a 2xx HTML body, for
 *   non-JSON callers that must not accept the login page as content.
 * @returns {Promise<any>}
 */
export async function post(route, params = {}, readMethod = "json", options = {}) {
    let formData = params;
    if (!(formData instanceof FormData)) {
        formData = new FormData();
        for (const [key, value] of Object.entries(params)) {
            if (Array.isArray(value)) {
                // One append per element; an empty array appends nothing
                // (appending it directly would serialize to "").
                for (const val of value) {
                    formData.append(key, val);
                }
            } else {
                formData.append(key, value);
            }
        }
    }
    const response = await browser.fetch(route, {
        body: /** @type {any} */ (formData),
        method: "POST",
    });
    checkResponseStatus(response, readMethod, options);
    return /** @type {any} */ (response)[readMethod]();
}

export const httpService = {
    // Wires destroy-protection at `useService("http")` time so a component
    // unmounting mid-fetch won't resume into destroyed state on response.
    // See `hooks.js:_protectMethod`.
    async: ["get", "post"],
    start() {
        return { get, post };
    },
};

registry.category("services").add("http", httpService);
