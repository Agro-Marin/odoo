// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/special_data_cache */

const DEFAULT_LIMIT = 512;

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
