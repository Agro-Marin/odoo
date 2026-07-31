// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/global_singleton */

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
    return (store[key] ??= factory());
}
