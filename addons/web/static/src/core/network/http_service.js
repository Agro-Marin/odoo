// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import {
    ConnectionLostError,
    InvalidResponseError,
    NetworkError,
    RequestEntityTooLargeError,
} from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * @param {Response} response
 * @param {string} [readMethod]
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
 * @param {{ rejectHtml?: boolean }} [options]
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
 * @param {{ rejectHtml?: boolean }} [options]
 * @returns {Promise<any>}
 */
export async function post(route, params = {}, readMethod = "json", options = {}) {
    let formData = params;
    if (!(formData instanceof FormData)) {
        formData = new FormData();
        for (const [key, value] of Object.entries(params)) {
            if (Array.isArray(value)) {
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

const httpService = {
    async: ["get", "post"],
    start() {
        return { get, post };
    },
};

registry.category("services").add("http", httpService);
