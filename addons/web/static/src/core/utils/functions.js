// @ts-check
/** @odoo-module native */

import { globalSingleton } from "@web/core/utils/global_singleton";

/**
 * @template {(...args: any[]) => any} T
 * @param {T} func
 * @returns {T}
 */
export function memoize(func) {
    /** @type {Map<number, Map<any, any>>} */
    const cachesByArity = new Map();
    const funcName = func.name ? `${func.name} (memoized)` : "memoized";
    return /** @type {any} */ (
        {
            [funcName](/** @type {any[]} */ ...args) {
                let node = cachesByArity.get(args.length);
                if (!node) {
                    node = new Map();
                    cachesByArity.set(args.length, node);
                }
                for (let i = 0; i < args.length - 1; i++) {
                    /** @type {Map<any, any>} */
                    let next = node.get(args[i]);
                    if (!next) {
                        next = new Map();
                        node.set(args[i], next);
                    }
                    node = next;
                }
                const key = args.length ? args[args.length - 1] : undefined;
                if (!node.has(key)) {
                    const value = func(...args);
                    const leaf = node;
                    leaf.set(key, value);
                    if (value && typeof value.then === "function") {
                        Promise.resolve(value).catch(() => {
                            if (leaf.get(key) === value) {
                                leaf.delete(key);
                            }
                        });
                    }
                }
                return node.get(key);
            },
        }[funcName]
    );
}

/**
 * @param {string} prefix
 * @returns {string}
 */
export function uniqueId(prefix = "") {
    return `${prefix}${++uniqueId.nextId}`;
}
const _uidState = globalSingleton("uniqueId", () => ({ nextId: 0 }));
Object.defineProperty(uniqueId, "nextId", {
    configurable: true,
    get: () => _uidState.nextId,
    set: (value) => {
        _uidState.nextId = value;
    },
});
