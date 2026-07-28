// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/storage_json - Fault-tolerant JSON reads from Web Storage */

import { browser } from "@web/core/browser/browser";

/**
 * Read and parse a JSON value from ``localStorage``, degrading to ``fallback``
 * on every failure mode instead of throwing into the caller.
 *
 * Three things go wrong here and each one had its own hand-rolled, subtly
 * different guard before this helper existed:
 *
 * 1. **Storage throws.** Private mode, a sandboxed iframe or a disabled
 *    cookie policy makes ``getItem`` itself throw. A service reading at
 *    ``start()`` would take itself — and its dependents — down on every boot.
 * 2. **The payload is not JSON.** A truncated or hand-edited value.
 * 3. **The payload is VALID JSON of the wrong shape.** The nasty one, and the
 *    reason ``validate`` exists rather than a bare try/catch: ``JSON.parse``
 *    happily returns ``null``, a number or a string, all of which sail past a
 *    try/catch and then explode at the first ``Object.entries`` / ``.filter``
 *    — on every render, permanently bricking the feature until the user
 *    clears storage by hand.
 *
 * ``clearOnInvalid`` additionally evicts the bad key so the next read starts
 * clean. Use it where the value is an accumulating cache the app rewrites
 * anyway (a recent-users list), and leave it off where the entry is a user
 * setting another tab may be mid-write on.
 *
 * @template T
 * @param {string} key
 * @param {object} options
 * @param {T} options.fallback returned whenever the stored value is missing,
 *   unreadable, unparsable or rejected by ``validate``
 * @param {(value: any) => boolean} [options.validate] shape check applied to
 *   the parsed value; anything it rejects degrades to ``fallback``
 * @param {boolean} [options.clearOnInvalid=false] remove the key when the
 *   stored value is present but unusable
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
            } catch {
                // Storage went away between the read and the eviction; the
                // fallback below is still the correct answer.
            }
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
 * Serialize and store a JSON value, swallowing storage failures.
 *
 * Quota exhaustion and private-mode rejection are both ``setItem`` throwing.
 * Every caller here is persisting an optimisation or a preference, never
 * something the app cannot proceed without, so a failed write must not
 * propagate.
 *
 * @param {string} key
 * @param {any} value
 * @returns {boolean} whether the write landed
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
 * Whether ``value`` is a plain object — the shape a ``Record<string, …>``
 * cache expects, and specifically NOT ``null`` or an array, both of which are
 * ``typeof "object"`` and both of which reach ``Object.entries`` unharmed
 * before failing somewhere less obvious.
 *
 * @param {any} value
 * @returns {boolean}
 */
export function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
