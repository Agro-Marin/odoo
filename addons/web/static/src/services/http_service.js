// @ts-check
/** @odoo-module native */

/** @module @web/services/http_service - Simple HTTP GET/POST helpers with status checking and FormData support */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

/**
 * @param {Response} response
 */
function checkResponseStatus(response) {
    if (response.status >= 502 && response.status <= 504) {
        // 502 Bad Gateway / 503 Service Unavailable / 504 Gateway Timeout
        throw new Error("Failed to fetch");
    }
    if (response.status === 413) {
        throw new Error("Content too large");
    }
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
            if (Array.isArray(value) && value.length) {
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
