// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/list_membership */

/** @import { RelationalRecord } from "./record.js" */

/**
 * The membership ledger of a {@link StaticList}: the ordered id list, the page
 * of materialised records, and the pager total.
 *
 * `count` is DERIVED, not stored. It used to be a field that every mutator had
 * to keep in step with `ids` by hand -- ~12 sites across three files, each one
 * an opportunity to drift, and the reason `_load` once needed a multiset
 * difference just to work out how far `count` had fallen behind. Making it a
 * getter is what makes `count !== ids.length` unrepresentable rather than
 * merely untested.
 */
export class ListMembership {
    /** @param {(number | string)[]} [ids] */
    constructor(ids = []) {
        this.ids = [...ids];
        /** @type {RelationalRecord[]} */
        this.records = [];
        this.tmpIncreaseLimit = 0;
    }

    /**
     * The number of members, i.e. the x2many pager total.
     *
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
     * @param {Record<string | number, any>} cache
     * @param {number} offset
     * @param {number} limit
     * @returns {any[]}
     */
    materialize(cache, offset, limit) {
        this.records = this.ids
            .slice(offset, offset + limit)
            .map((id) => cache[id])
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
