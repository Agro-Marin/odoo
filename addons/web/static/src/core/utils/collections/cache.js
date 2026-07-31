// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/collections/cache */

/**
 * @param {any} segment
 */
function assertPrimitiveSegment(segment) {
    const type = typeof segment;
    if (
        segment === null ||
        segment === undefined ||
        type === "object" ||
        type === "function"
    ) {
        throw new TypeError(
            `Cache: invalid path segment ${String(segment)} (${segment === null ? "null" : type}). ` +
                "Without a getKey function, path segments must be primitive (string, number, " +
                "boolean, bigint, or symbol). Pass a getKey (e.g. JSON.stringify) to key on objects.",
        );
    }
}

/**
 * @template T
 */
export class Cache {
    /**
     * @param {(...args: any[]) => T} getValue
     * @param {((...args: any[]) => string) | undefined} [getKey]
     */
    constructor(getValue, getKey) {
        /** @type {Record<string, any>} */
        this.cache = Object.create(null);
        this.getKey = getKey;
        this.getValue = getValue;
    }

    /**
     * @param {any[]} path
     * @param {boolean} create
     * @returns {{ cache: Record<string, any> | null, key: string }}
     */
    _getCacheAndKey(path, create) {
        let cache = this.cache;
        let key;
        if (this.getKey) {
            key = this.getKey(...path);
        } else {
            if (!path.length) {
                throw new TypeError(
                    "Cache: a lookup path must have at least one segment.",
                );
            }
            for (const segment of path) {
                assertPrimitiveSegment(segment);
            }
            for (let i = 0; i < path.length - 1; i++) {
                if (!cache[path[i]]) {
                    if (!create) {
                        return { cache: null, key: String(path.at(-1)) };
                    }
                    cache[path[i]] = Object.create(null);
                }
                cache = cache[path[i]];
            }
            key = path.at(-1);
        }
        return { cache, key };
    }

    /**
     * @param {any[]} path
     */
    clear(...path) {
        const { cache, key } = this._getCacheAndKey(path, false);
        if (cache) {
            delete cache[key];
        }
    }

    invalidate() {
        this.cache = Object.create(null);
    }

    /**
     * @param {T} value
     * @param {any[]} path
     */
    set(value, ...path) {
        const { cache, key } = this._getCacheAndKey(path, true);
        /** @type {Record<string, any>} */ (cache)[key] = value;
    }

    /**
     * @param {any[]} path
     * @returns {T}
     */
    read(...path) {
        const { cache: node, key } = this._getCacheAndKey(path, true);
        const cache = /** @type {Record<string, any>} */ (node);
        if (!(key in cache)) {
            const value = this.getValue(...path);
            cache[key] = value;
            if (value && typeof (/** @type {any} */ (value).then) === "function") {
                Promise.resolve(value).catch(() => {
                    if (cache[key] === value) {
                        delete cache[key];
                    }
                });
            }
        }
        return cache[key];
    }
}
