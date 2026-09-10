// @ts-check
/** @odoo-module native */

const NAMESPACE = "__odoo_singletons__";

/**
 * @template T
 * @param {string} key
 * @param {() => T} factory
 * @returns {T}
 */
export function globalSingleton(key, factory) {
    const root = /** @type {Record<string, Record<string, any>>} */ (
        /** @type {any} */ (globalThis)
    );
    const store = (root[NAMESPACE] ??= Object.create(null));
    if (!(key in store)) {
        store[key] = factory();
    }
    return store[key];
}
