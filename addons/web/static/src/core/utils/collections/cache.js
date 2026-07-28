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
     * Resolve ``path`` to the node holding its entry, plus the key within it.
     *
     * ``create`` distinguishes a WRITE — which must materialise the intermediate
     * nodes it will hang the value off — from a READ-ONLY probe. Without it,
     * ``clear("never", "registered")`` grew a ``{ never: {} }`` branch on its way
     * to deleting nothing: a cache-eviction call that made the cache bigger.
     *
     * @param {any[]} path
     * @param {boolean} create materialise missing intermediate nodes
     * @returns {{ cache: Record<string, any> | null, key: string }} ``cache`` is
     *   null when a read-only probe found no such branch.
     */
    _getCacheAndKey(path, create) {
        let cache = this.cache;
        let key;
        if (this.getKey) {
            key = this.getKey(...path);
        } else {
            // An empty path produces `key === undefined` and therefore keys on
            // the STRING "undefined" — silently sharing one slot with a genuine
            // `read("undefined")`, and skipping the segment check below
            // entirely. Same class of silent collision `assertPrimitiveSegment`
            // exists to prevent, so it is rejected the same way.
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
     * Remove a single cached entry identified by `path`.
     *
     * @param {any[]} path
     */
    clear(...path) {
        const { cache, key } = this._getCacheAndKey(path, false);
        if (cache) {
            delete cache[key];
        }
    }

    /** Flush the entire cache. */
    invalidate() {
        this.cache = Object.create(null);
    }

    /**
     * Store a value for `path` without ever calling `getValue`, for entries the
     * caller already has in hand (e.g. group memberships shipped in the session,
     * which must not cost a `has_group` round-trip).
     *
     * Seeding by writing to `cache` directly — as `@web/services/user` did —
     * bypasses {@link _getCacheAndKey}, so it only lands on the key `read` looks
     * up while `getKey` happens to be the identity of the first path segment.
     * Any change to `getKey` would silently turn every seeded entry into an
     * unreachable one, and the misses would look like ordinary cache misses.
     *
     * @param {T} value
     * @param {any[]} path
     */
    set(value, ...path) {
        const { cache, key } = this._getCacheAndKey(path, true);
        /** @type {Record<string, any>} */ (cache)[key] = value;
    }

    /**
     * Return the cached value for `path`, computing it via `getValue` if absent.
     *
     * @param {any[]} path
     * @returns {T}
     */
    read(...path) {
        const { cache: node, key } = this._getCacheAndKey(path, true);
        const cache = /** @type {Record<string, any>} */ (node);
        if (!(key in cache)) {
            const value = this.getValue(...path);
            cache[key] = value;
            if (value && typeof value.then === "function") {
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
