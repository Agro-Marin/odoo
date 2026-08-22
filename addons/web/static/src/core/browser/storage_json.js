// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";

/**
 * @template T
 * @param {string} key
 * @param {object} options
 * @param {T} options.fallback
 * @param {(value: any) => boolean} [options.validate]
 * @param {boolean} [options.clearOnInvalid=false]
 * @returns {T}
 */
export function readJSONStorage(key, { fallback, validate, clearOnInvalid = false }) {
    /** @type {string | null} */
    let raw;
    try {
        raw = browser.localStorage.getItem(key);
    } catch {
        return fallback;
    }
    if (raw === null || raw === undefined) {
        return fallback;
    }
    const discard = () => {
        if (clearOnInvalid) {
            try {
                browser.localStorage.removeItem(key);
            } catch {}
        }
        return fallback;
    };
    let parsed;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return discard();
    }
    if (validate && !validate(parsed)) {
        return discard();
    }
    return parsed;
}

/**
 * @param {string} key
 * @param {any} value
 * @returns {boolean}
 */
export function writeJSONStorage(key, value) {
    try {
        browser.localStorage.setItem(key, JSON.stringify(value));
        return true;
    } catch {
        return false;
    }
}

/**
 * @param {any} value
 * @returns {boolean}
 */
export function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
