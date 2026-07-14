/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @typedef {import("./record_list").RecordList} RecordList */

export class RecordUses {
    /**
     * Track the uses of a record. Each record contains a single `RecordUses`:
     * - Key: record that uses current record. Keyed by reference, not by
     *   localId: localId strings are reusable after delete + re-insert,
     *   which would alias stale entries onto the new record.
     * - Value: Map where key is relational field name, and value is number
     *          of time current record is present in this relation.
     *
     * @type {Map<Record, Map<string, number>>}
     */
    data = new Map();
    /** @param {RecordList} list */
    add(list) {
        const record = list._.owner;
        let use = this.data.get(record);
        if (!use) {
            use = new Map();
            this.data.set(record, use);
        }
        use.set(list._.name, (use.get(list._.name) ?? 0) + 1);
    }
    /** @param {RecordList} list */
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
