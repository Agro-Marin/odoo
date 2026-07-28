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
const _uidState = /** @type {{ nextId: number }} */ (
    /** @type {any} */ (globalThis).__odoo_uid_state__ ??= { nextId: 0 }
);
Object.defineProperty(uniqueId, "nextId", {
    configurable: true,
    get: () => _uidState.nextId,
    set: (value) => {
        _uidState.nextId = value;
    },
});
