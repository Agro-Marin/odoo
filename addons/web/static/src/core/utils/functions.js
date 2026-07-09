// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/functions - memoize and uniqueId general-purpose function helpers */

/**
 * Creates a version of the function that's memoized on the value of its first
 * argument, if any.
 *
 * @template T, U
 * @param {(arg: T) => U} func the function to memoize
 * @returns {(arg: T) => U} a memoized version of the original function
 */
export function memoize(func) {
    const cache = new Map();
    const funcName = func.name ? `${func.name} (memoized)` : "memoized";
    return {
        [funcName](/** @type {any[]} */ ...args) {
            if (!cache.has(args[0])) {
                const value = /** @type {any} */ (func)(...args);
                cache.set(args[0], value);
                if (value && typeof value.then === "function") {
                    // A cached promise that later rejects would otherwise
                    // poison this slot forever: every subsequent call returns
                    // the same rejected promise and the value is never
                    // recomputed. Evict on rejection so the next call retries
                    // (same contract as collections/cache.js Cache.read).
                    Promise.resolve(value).catch(() => {
                        if (cache.get(args[0]) === value) {
                            cache.delete(args[0]);
                        }
                    });
                }
            }
            return cache.get(args[0]);
        },
    }[funcName];
}

/**
 * Generate a unique integer id (unique within the entire client session).
 * Useful for temporary DOM ids.
 *
 * @param {string} prefix
 * @returns {string}
 */
export function uniqueId(prefix = "") {
    return `${prefix}${++uniqueId.nextId}`;
}
// set nextId on the function itself to be able to patch then
uniqueId.nextId = 0;
