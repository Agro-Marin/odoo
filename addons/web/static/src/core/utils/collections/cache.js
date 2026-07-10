// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/collections/cache - Generic key-path cache with lazy value computation */

/**
 * Reject a path segment that cannot serve as a distinct string cache key.
 *
 * Only meaningful when no `getKey` is provided: objects and functions all
 * coerce to a shared string ("[object Object]", function source) and would
 * silently collide, and `null` / `undefined` collide with the literal strings
 * "null" / "undefined". A `symbol` is a legitimate distinct key and is allowed.
 *
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
 * A generic cache that stores values indexed by a key derived from the lookup
 * path. When a value is not found, it is computed via the `getValue` callback
 * and stored for future reads.
 *
 * @template T
 */
export class Cache {
    /**
     * @param {(...args: any[]) => T} getValue called to compute a missing value
     * @param {((...args: any[]) => string) | undefined} [getKey] derives a flat
     *   cache key from the path arguments. When omitted, the path is used to
     *   build a nested object structure with the last segment as key.
     */
    constructor(getValue, getKey) {
        /** @type {Record<string, any>} */
        this.cache = Object.create(null);
        this.getKey = getKey;
        this.getValue = getValue;
    }

    /**
     * @param {any[]} path
     * @returns {{ cache: Record<string, any>, key: string }}
     */
    _getCacheAndKey(...path) {
        let cache = this.cache;
        let key;
        if (this.getKey) {
            key = this.getKey(...path);
        } else {
            // Fail fast on non-primitive segments here (see assertPrimitiveSegment)
            // instead of letting them silently collide once coerced to object keys.
            for (const segment of path) {
                assertPrimitiveSegment(segment);
            }
            for (let i = 0; i < path.length - 1; i++) {
                cache = cache[path[i]] = cache[path[i]] || Object.create(null);
            }
            key = path.at(-1);
        }
        return { cache, key };
    }

    /**
     * Remove a single cached entry identified by `path`.
     *
     * @param {any[]} path
     */
    clear(...path) {
        const { cache, key } = this._getCacheAndKey(...path);
        delete cache[key];
    }

    /** Flush the entire cache. */
    invalidate() {
        this.cache = Object.create(null);
    }

    /**
     * Return the cached value for `path`, computing it via `getValue` if absent.
     *
     * @param {any[]} path
     * @returns {T}
     */
    read(...path) {
        const { cache, key } = this._getCacheAndKey(...path);
        if (!(key in cache)) {
            const value = this.getValue(...path);
            cache[key] = value;
            if (value && typeof value.then === "function") {
                // A cached promise that later rejects would otherwise poison
                // this slot forever: every subsequent read returns the same
                // rejected promise and the value is never recomputed. Evict on
                // rejection so the next read retries. The identity guard leaves
                // a successful re-read (or invalidate/clear) that already
                // replaced this slot untouched.
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
