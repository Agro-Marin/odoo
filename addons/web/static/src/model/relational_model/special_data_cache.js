// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/special_data_cache - Bounded LRU cache for per-model special-data reads */

/** Entries retained before the least-recently-used one is dropped. */
const DEFAULT_LIMIT = 512;

/**
 * Bounded, least-recently-used cache for the "special data" a model reads on
 * behalf of its field widgets: reference display names
 * (``@web/fields/relational/reference/reference_field``) and selection option
 * lists (``@web/fields/relational/special_data``).
 *
 * It replaces a plain object that had no bound and no eviction — the only
 * ``delete`` calls were error-path cleanups. Both writers key per *datum*
 * rather than per *field*: ``ReferenceField`` on ``"<model>,<id>"``, so one
 * entry is retained for every referenced record ever displayed, and
 * ``useSpecialData`` on the full RPC argument list, so one entry per distinct
 * (domain, context) pair. ``RelationalModel.exportState`` hands the cache to
 * the next model instance, so it outlived any single view and grew for the
 * life of the tab.
 *
 * Entries are pure memoized reads, so dropping one only costs a refetch —
 * which makes a bound strictly safer than unbounded retention.
 *
 * A ``Map`` iterates in insertion order, so the least-recently-used key is
 * always ``keys().next()``. Both ``get`` and ``set`` reinsert, which is what
 * makes the ordering recency rather than plain first-in-first-out.
 */
export class SpecialDataCache {
    /** @param {number} [limit] */
    constructor(limit = DEFAULT_LIMIT) {
        this.limit = limit;
        /** @type {Map<string, any>} */
        this._entries = new Map();
    }

    /** @returns {number} */
    get size() {
        return this._entries.size;
    }

    /**
     * @param {string} key
     * @returns {boolean}
     */
    has(key) {
        return this._entries.has(key);
    }

    /**
     * Reads an entry and marks it most-recently-used.
     *
     * @param {string} key
     * @returns {any}
     */
    get(key) {
        if (!this._entries.has(key)) {
            return undefined;
        }
        const value = this._entries.get(key);
        this._entries.delete(key);
        this._entries.set(key, value);
        return value;
    }

    /**
     * @param {string} key
     * @param {any} value
     * @returns {this}
     */
    set(key, value) {
        this._entries.delete(key);
        this._entries.set(key, value);
        while (this._entries.size > this.limit) {
            this._entries.delete(
                /** @type {string} */ (this._entries.keys().next().value),
            );
        }
        return this;
    }

    /**
     * @param {string} key
     * @returns {boolean}
     */
    delete(key) {
        return this._entries.delete(key);
    }
}
