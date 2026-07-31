// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_cache */

const BREADCRUMB_CACHE_LIMIT = 200;

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
     * @param {string} key
     * @returns {any}
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
     * @param {string} key
     * @param {any} value
     */
    set(key, value) {
        if (this._entries.delete(key)) {
            // Re-inserting is what moves the entry back to the hot end: a plain
            // `Map.set` on an existing key keeps its original position.
            this._entries.set(key, value);
            return;
        }
        if (this._entries.size >= this._limit) {
            const coldest = this._entries.keys().next().value;
            this._entries.delete(coldest);
        }
        this._entries.set(key, value);
    }

    /**
     * @param {string} key
     */
    touch(key) {
        this.get(key);
    }

    /** @param {string} key */
    delete(key) {
        this._entries.delete(key);
    }

    clear() {
        this._entries.clear();
    }

    /** @returns {number} */
    get size() {
        return this._entries.size;
    }
}
