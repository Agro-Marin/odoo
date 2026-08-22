// @ts-check
/** @odoo-module native */

/** @import { RelationalRecord } from "./record.js" */

export class ListMembership {
    /** @param {(number | string)[]} [ids] */
    constructor(ids = []) {
        this.ids = [...ids];
        /** @type {RelationalRecord[]} */
        this.records = [];
        this.tmpIncreaseLimit = 0;
    }

    /**
     * @returns {number}
     */
    get count() {
        return this.ids.length;
    }

    /** @returns {number} */
    get length() {
        return this.ids.length;
    }

    /**
     * @param {Map<number | string, any>} cache
     * @param {number} offset
     * @param {number} limit
     * @returns {any[]}
     */
    materialize(cache, offset, limit) {
        this.records = this.ids
            .slice(offset, offset + limit)
            .map((id) => cache.get(id))
            .filter(Boolean);
        return this.records;
    }

    /**
     * @param {number} offset
     * @param {number} limit
     * @returns {number | null}
     */
    clampedOffset(offset, limit) {
        if (offset === 0 || offset < this.ids.length) {
            return null;
        }
        return this.ids.length && limit > 0
            ? Math.floor((this.ids.length - 1) / limit) * limit
            : 0;
    }

    /**
     * @param {number} index
     * @param {number | string} id
     * @returns {void}
     */
    insertAt(index, id) {
        this.ids.splice(index, 0, id);
    }

    /**
     * @param {number | string} id
     * @returns {void}
     */
    append(id) {
        this.ids.push(id);
    }

    /**
     * @param {number | string} id
     * @param {any} [record]
     * @returns {boolean}
     */
    removeMember(id, record) {
        const index = this.ids.findIndex((currentId) => currentId === id);
        if (index < 0) {
            return false;
        }
        this.ids.splice(index, 1);
        if (record) {
            const recordIndex = this.records.findIndex((r) => r === record);
            if (recordIndex >= 0) {
                this.records.splice(recordIndex, 1);
            }
        }
        return true;
    }
}
