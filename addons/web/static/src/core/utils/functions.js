// @ts-check
/** @odoo-module native */

import { globalSingleton } from "@web/core/utils/global_singleton";

/**
 * A map that holds object keys weakly and everything else strongly.
 *
 * `memoize` keys on argument IDENTITY, so a plain `Map` pins every object ever
 * passed to a memoized function for the life of the page. Several callers do
 * exactly that -- `memoize((element) => new TableOfContentManager(...))` keys on
 * a DOM node, `memoize((button) => button.isAvailable(...))` on a component --
 * and none of them can ever release what they cached. Weak keys change no
 * semantics: an entry is only ever dropped once nothing else can ask for it,
 * because asking requires holding the key.
 */
class IdentityKeyMap {
    constructor() {
        /** @type {Map<any, any>} */
        this._strong = new Map();
        /** @type {WeakMap<object, any>} */
        this._weak = new WeakMap();
    }
    /**
     * @param {any} key
     * @returns {Map<any, any> | WeakMap<object, any>}
     */
    _mapFor(key) {
        // Symbols are left strong: they are cheap, bounded in practice, and
        // only became legal WeakMap keys recently.
        return key !== null && (typeof key === "object" || typeof key === "function")
            ? this._weak
            : this._strong;
    }
    /** @param {any} key */
    has(key) {
        return this._mapFor(key).has(key);
    }
    /** @param {any} key */
    get(key) {
        return this._mapFor(key).get(key);
    }
    /**
     * @param {any} key
     * @param {any} value
     */
    set(key, value) {
        this._mapFor(key).set(key, value);
    }
    /** @param {any} key */
    delete(key) {
        return this._mapFor(key).delete(key);
    }
}

/**
 * @template {(...args: any[]) => any} T
 * @param {T} func
 * @returns {T}
 */
export function memoize(func) {
    /** @type {Map<number, IdentityKeyMap>} */
    const cachesByArity = new Map();
    const funcName = func.name ? `${func.name} (memoized)` : "memoized";
    return /** @type {any} */ (
        {
            [funcName](/** @type {any[]} */ ...args) {
                let node = cachesByArity.get(args.length);
                if (!node) {
                    node = new IdentityKeyMap();
                    cachesByArity.set(args.length, node);
                }
                for (let i = 0; i < args.length - 1; i++) {
                    /** @type {IdentityKeyMap} */
                    let next = node.get(args[i]);
                    if (!next) {
                        next = new IdentityKeyMap();
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
