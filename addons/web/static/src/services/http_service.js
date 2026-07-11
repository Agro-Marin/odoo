// @ts-check
/** @odoo-module native */

/** @module @web/services/http_service - Simple HTTP GET/POST helpers with status checking and FormData support */

import { browser } from "@web/core/browser/browser";
import {
    ConnectionLostError,
    NetworkError,
    RequestEntityTooLargeError,
} from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * Throw a classified error (rpc.js hierarchy, so callers and error handlers
 * can branch on it) for non-ok statuses instead of falling through to an
 * opaque body-parse failure on HTML error pages.
 *
 * @param {Response} response
 */
function checkResponseStatus(response) {
    if (response.ok) {
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
 * @returns {Promise<any>}
 */
export async function get(route, readMethod = "json") {
    const response = await browser.fetch(route, { method: "GET" });
    checkResponseStatus(response);
    return /** @type {any} */ (response)[readMethod]();
}

/**
 * @param {string} route
 * @param {Record<string, any> | FormData} [params={}]
 * @param {string} [readMethod="json"]
 * @returns {Promise<any>}
 */
export async function post(route, params = {}, readMethod = "json") {
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
    checkResponseStatus(response);
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
