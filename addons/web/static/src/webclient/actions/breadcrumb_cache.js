// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_cache - Bounded LRU cache of breadcrumb display names, keyed by {action, model, resId} */

/**
 * Maximum number of entries. The cache is otherwise only flushed on
 * ``ir.actions.act_window`` writes, so in a long-lived session it would grow one
 * entry per unique ``{action, model, resId}`` visited, unboundedly.
 */
const BREADCRUMB_CACHE_LIMIT = 200;

/**
 * Bounded LRU cache mapping a serialized ``{action, model, resId}`` key to a
 * breadcrumb result — either a resolved ``{display_name}`` or the in-flight
 * Promise for one (callers await whatever they get back, so a concurrent
 * second visit to the same record joins the first fetch instead of issuing its
 * own).
 *
 * NOTE — flushing is done by REPLACING the instance
 * (``am.breadcrumbCache = new BreadcrumbCache()``), not by {@link clear}. That
 * is load-bearing: ``fetchBreadcrumbs`` captures the cache by reference and
 * writes its results in a ``.then``, so an RPC issued BEFORE the invalidating
 * write commits resolves with pre-write display names. Replacing the instance
 * orphans that stale result; clearing in place would let it repopulate the live
 * cache with exactly the names the flush was meant to discard.
 */
export class BreadcrumbCache {
    /** @param {number} [limit] */
    constructor(limit = BREADCRUMB_CACHE_LIMIT) {
        /** @type {Map<string, any>} */
        this._entries = new Map();
        this._limit = limit;
    }

    /** @param {string} key */
    has(key) {
        return this._entries.has(key);
    }

    /**
     * Read an entry, marking it as recently used.
     * @param {string} key
     * @returns {any} the cached value, or ``undefined``
     */
    get(key) {
        if (!this._entries.has(key)) {
            return undefined;
        }
        const hit = this._entries.get(key);
        this._entries.delete(key);
        this._entries.set(key, hit);
        return hit;
    }

    /**
     * Write an entry, evicting the coldest one when full.
     * @param {string} key
     * @param {any} value
     */
    set(key, value) {
        if (!this._entries.has(key) && this._entries.size >= this._limit) {
            const coldest = this._entries.keys().next().value;
            this._entries.delete(coldest);
        }
        this._entries.set(key, value);
    }

    /** @param {string} key */
    delete(key) {
        this._entries.delete(key);
    }

    /**
     * Drop every entry in place.
     *
     * NOT the way to flush after an ``ir.actions.act_window`` write — see the
     * NOTE on the class. Use it only when no fetch can be in flight (tests,
     * teardown).
     */
    clear() {
        this._entries.clear();
    }

    /** @returns {number} current entry count (diagnostics/tests) */
    get size() {
        return this._entries.size;
    }
}
