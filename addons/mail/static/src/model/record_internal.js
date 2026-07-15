/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @typedef {import("./record_list").RecordList} RecordList */

import { reactive, toRaw } from "@odoo/owl";

import { IS_DELETED_SYM, IS_RECORD_SYM, isRelation } from "./misc.js";
import { RecordList } from "./record_list.js";
import { RecordUses } from "./record_uses.js";

export class RecordInternal {
    [IS_RECORD_SYM] = true;
    // Note: state of fields in Maps rather than object is intentional for improved performance.
    /** @type {Map<string, () => void>} */
    fieldsOnUpdateObserves = new Map();
    /** @type {Map<string, this>} */
    fieldsSortProxy2 = new Map();
    /** @type {Map<string, this>} */
    fieldsComputeProxy2 = new Map();
    uses = new RecordUses();
    updatingAttrs = new Map();
    proxyUsed = new Map();
    /** @type {string} */
    localId;
    gettingField = 0;

    /**
     * @param {Record} record
     * @param {string} fieldName
     * @param {Record} recordProxy
     */
    prepareField(record, fieldName, recordProxy) {
        const self = this;
        const Model = toRaw(record).Model;
        if (isRelation(Model, fieldName)) {
            // Relational fields contain symbols for detection in original class.
            // This constructor is called on genuine records:
            // - 'one' fields => undefined
            // - 'many' fields => RecordList
            // record[name]?.[0] is ONE_SYM or MANY_SYM
            const recordList = new RecordList();
            Object.assign(recordList._, {
                name: fieldName,
                owner: record,
            });
            Object.assign(recordList, {
                _raw: recordList,
                _store: record.store,
            });
            record[fieldName] = recordList;
        } else {
            const def = Model._.fieldsDefault.get(fieldName);
            if (typeof def === "object" && def !== null) {
                // mutable default (e.g. fields.Attr([])): each record must get
                // its own instance, so read it from the per-instance definition
                // object allocated by the class-field initializer
                record[fieldName] = record[fieldName].default;
            } else {
                // primitive default: read from the Model-level definition
                // cache; the per-instance definition object is never consulted
                record[fieldName] = def;
            }
        }
        if (Model._.fieldsCompute.get(fieldName)) {
            const cb = function computeObserver() {
                self.requestCompute(record, fieldName);
            };
            const computeProxy2 = reactive(recordProxy, cb);
            this.fieldsComputeProxy2.set(fieldName, computeProxy2);
        }
        if (Model._.fieldsSort.get(fieldName)) {
            const sortProxy2 = reactive(recordProxy, function sortObserver() {
                self.requestSort(record, fieldName);
            });
            this.fieldsSortProxy2.set(fieldName, sortProxy2);
        }
        if (Model._.fieldsOnUpdate.get(fieldName)) {
            const store = Model.store;
            store._onChange(recordProxy, fieldName, (obs) => {
                this.fieldsOnUpdateObserves.set(fieldName, obs);
                if (store._.UPDATE !== 0) {
                    store._.ADD_QUEUE("onUpdate", record, fieldName);
                } else {
                    this.onUpdate(record, fieldName);
                }
            });
        }
    }

    requestCompute(record, fieldName, { force = false } = {}) {
        if (record[IS_DELETED_SYM]) {
            return;
        }
        const Model = record.Model;
        if (!Model._.fieldsCompute.get(fieldName)) {
            return;
        }
        const store = record._rawStore;
        if (store._.UPDATE !== 0 && !force) {
            store._.ADD_QUEUE("compute", record, fieldName);
        } else {
            this.compute(record, fieldName);
        }
    }
    requestSort(record, fieldName, { force } = {}) {
        if (record[IS_DELETED_SYM]) {
            return;
        }
        const Model = record.Model;
        if (!Model._.fieldsSort.get(fieldName)) {
            return;
        }
        const store = record._rawStore;
        if (store._.UPDATE !== 0 && !force) {
            store._.ADD_QUEUE("sort", record, fieldName);
        } else {
            this.sort(record, fieldName);
        }
    }
    /**
     * @param {Record} record
     * @param {string} fieldName
     */
    compute(record, fieldName) {
        const Model = record.Model;
        const store = record._rawStore;
        let computedValue;
        try {
            computedValue = Model._.fieldsCompute
                .get(fieldName)
                .call(this.fieldsComputeProxy2.get(fieldName));
        } catch (err) {
            store.handleError(err);
        }
        store._.updateFields(record, {
            [fieldName]: computedValue,
        });
    }
    /**
     * @param {Record} record
     * @param {string} fieldName
     */
    sort(record, fieldName) {
        const Model = record.Model;
        if (!Model._.fieldsSort.get(fieldName)) {
            return;
        }
        const store = record._rawStore;
        const proxy2Sort = this.fieldsSortProxy2.get(fieldName);
        const func = Model._.fieldsSort.get(fieldName).bind(proxy2Sort);
        if (isRelation(Model, fieldName)) {
            try {
                store._.sortRecordList(proxy2Sort[fieldName]._proxy, func);
            } catch (err) {
                store.handleError(err);
            }
        } else {
            // sort on copy of list so that reactive observers not triggered while sorting
            const copy = [...proxy2Sort[fieldName]];
            copy.sort(func);
            const hasChanged = copy.some(
                (item, index) => item !== record[fieldName][index],
            );
            if (hasChanged) {
                proxy2Sort[fieldName] = copy;
            }
        }
    }
    onUpdate(record, fieldName) {
        const store = record._rawStore;
        const Model = record.Model;
        if (!Model._.fieldsOnUpdate.get(fieldName)) {
            return;
        }
        /**
         * Forward internal proxy for performance as onUpdate does not
         * need reactive (observe is called separately).
         */
        try {
            Model._.fieldsOnUpdate.get(fieldName).call(record._proxyInternal);
        } catch (err) {
            store.handleError(err);
        }
        this.fieldsOnUpdateObserves.get(fieldName)?.();
    }
    /**
     * The internal reactive is only necessary to trigger outer reactives when
     * writing on it. As it has no callback, reading through it has no effect,
     * except slowing down performance and complexifying the stack.
     */
    downgradeProxy(record, fullProxy) {
        return record._proxy === fullProxy ? record._proxyInternal : fullProxy;
    }
}
