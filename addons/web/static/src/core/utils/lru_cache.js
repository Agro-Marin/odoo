// @ts-check
/** @odoo-module native */

export class LruCache {
    /**
     * @param {number} limit
     * @param {{ onEvict?: (key: string, value: any) => void }} [options]
     */
    constructor(limit, { onEvict } = {}) {
        this.limit = limit;
        /** @type {((key: string, value: any) => void) | null} */
        this._onEvict = onEvict ?? null;
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
            const coldest = /** @type {string} */ (this._entries.keys().next().value);
            const evicted = this._entries.get(coldest);
            this._entries.delete(coldest);
            this._onEvict?.(coldest, evicted);
        }
        return this;
    }

    /**
     * @param {string} key
     * @returns {void}
     */
    touch(key) {
        this.get(key);
    }

    /**
     * @param {string} key
     * @returns {boolean}
     */
    delete(key) {
        return this._entries.delete(key);
    }

    /** @returns {void} */
    clear() {
        this._entries.clear();
    }
}
