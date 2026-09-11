// @ts-check
/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @import { RecordList } from "./record_list" */

export class RecordUses {
    /** @type {Map<Record, Map<string, number>>} */
    data = new Map();
    /**
     * @template {Record} R
     * @param {RecordList<R>} list
     */
    add(list) {
        const record = list._.owner;
        let use = this.data.get(record);
        if (!use) {
            use = new Map();
            this.data.set(record, use);
        }
        use.set(list._.name, (use.get(list._.name) ?? 0) + 1);
    }
    /**
     * @template {Record} R
     * @param {RecordList<R>} list
     */
    delete(list) {
        const record = list._.owner;
        const use = this.data.get(record);
        if (!use) {
            return;
        }
        const count = use.get(list._.name);
        if (!count) {
            return;
        }
        if (count === 1) {
            use.delete(list._.name);
            if (use.size === 0) {
                this.data.delete(record);
            }
        } else {
            use.set(list._.name, count - 1);
        }
    }
}
