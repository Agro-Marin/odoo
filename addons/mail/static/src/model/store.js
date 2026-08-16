/** @odoo-module native */
import { reactive, toRaw } from "@odoo/owl";

import { IS_DELETED_SYM, isRelation, modelRegistry, STORE_SYM } from "./misc.js";
import { Record } from "./record.js";

/** @typedef {import("./record_list").RecordList} RecordList */
/** @typedef {import("./record").RecordFields} RecordFields */
/** @typedef {import("./record").StoreModels} StoreModels */
export class Store extends Record {
    /**
     * @returns {any|void}
     */
    _makeInsertContext() {}
    /**
     * @param {any} ctx
     * @param {string} pyOrJsModelName
     * @returns {string}
     */
    _insertModelName(ctx, pyOrJsModelName) {
        return pyOrJsModelName;
    }
    /**
     * @param {string} pyOrJsModelName
     * @returns {Object|void}
     */
    _insertExtraFields(pyOrJsModelName) {}

    /** @type {import("./store_internal").StoreInternal} */
    _ = undefined;
    [STORE_SYM] = true;
    /** @type {Map<string, Record>} */
    recordByLocalId;
    storeReady = false;
    /**
     * @param {string} localId
     * @returns {Record}
     */
    get(localId) {
        return this.recordByLocalId.get(localId);
    }

    /**
     * @param {Error} err
     * @throws {Error}
     */
    handleError(err) {
        if (this._.UPDATE === 0) {
            if (this.warnErrors) {
                console.warn(err);
                return;
            }
            throw err;
        }
        this._.ERRORS.push(err);
    }

    warnErrors = true;

    /** @param {() => any} fn */
    MAKE_UPDATE(fn) {
        const outermost = this._.UPDATE === 0;
        this._.UPDATE++;
        let res;
        try {
            res = fn();
        } catch (err) {
            if (!outermost) {
                throw err;
            }
            this.handleError(err);
        } finally {
            this._.UPDATE--;
        }
        if (this._.UPDATE === 0) {
            const deletingRecordsByLocalId = new Map();
            this._.UPDATE++;
            let flushIterations = 0;
            try {
                while (
                    this._.FC_QUEUE.size > 0 ||
                    this._.FS_QUEUE.size > 0 ||
                    this._.FA_QUEUE.size > 0 ||
                    this._.FD_QUEUE.size > 0 ||
                    this._.FU_QUEUE.size > 0 ||
                    this._.RO_QUEUE.size > 0 ||
                    this._.RD_QUEUE.size > 0 ||
                    this._.RHD_QUEUE.size > 0
                ) {
                    if (++flushIterations > 1000) {
                        this.handleError(
                            new Error("Store flush did not converge (1000 iterations)"),
                        );
                        break;
                    }
                    const FC_QUEUE = new Map(this._.FC_QUEUE);
                    const FS_QUEUE = new Map(this._.FS_QUEUE);
                    const FA_QUEUE = new Map(this._.FA_QUEUE);
                    const FD_QUEUE = new Map(this._.FD_QUEUE);
                    const FU_QUEUE = new Map(this._.FU_QUEUE);
                    const RO_QUEUE = new Map(this._.RO_QUEUE);
                    const RD_QUEUE = new Map(this._.RD_QUEUE);
                    const RHD_QUEUE = new Map(this._.RHD_QUEUE);
                    this._.FC_QUEUE.clear();
                    this._.FS_QUEUE.clear();
                    this._.FA_QUEUE.clear();
                    this._.FD_QUEUE.clear();
                    this._.FU_QUEUE.clear();
                    this._.RO_QUEUE.clear();
                    this._.RD_QUEUE.clear();
                    this._.RHD_QUEUE.clear();
                    while (FC_QUEUE.size > 0) {
                        const [record, recMap] =
                            /** @type {[Record, Map<string, true>]} */ (
                                FC_QUEUE.entries().next().value
                            );
                        FC_QUEUE.delete(record);
                        for (const fieldName of recMap.keys()) {
                            record._.requestCompute(record, fieldName, { force: true });
                        }
                    }
                    while (FS_QUEUE.size > 0) {
                        const [record, recMap] =
                            /** @type {[Record, Map<string, true>]} */ (
                                FS_QUEUE.entries().next().value
                            );
                        FS_QUEUE.delete(record);
                        for (const fieldName of recMap.keys()) {
                            record._.requestSort(record, fieldName, { force: true });
                        }
                    }
                    while (FA_QUEUE.size > 0) {
                        const [record, recMap] =
                            /** @type {[Record, Map<string, Map<Record, true>>]} */ (
                                FA_QUEUE.entries().next().value
                            );
                        FA_QUEUE.delete(record);
                        while (recMap.size > 0) {
                            const [fieldName, fieldMap] =
                                /** @type {[string, Map<Record, true>]} */ (
                                    recMap.entries().next().value
                                );
                            recMap.delete(fieldName);
                            const onAdd = record.Model._.fieldsOnAdd.get(fieldName);
                            for (const addedRec of fieldMap.keys()) {
                                try {
                                    onAdd?.call(record._proxy, addedRec._proxy);
                                } catch (err) {
                                    this.handleError(err);
                                }
                            }
                        }
                    }
                    while (FD_QUEUE.size > 0) {
                        const [record, recMap] =
                            /** @type {[Record, Map<string, Map<Record, true>>]} */ (
                                FD_QUEUE.entries().next().value
                            );
                        FD_QUEUE.delete(record);
                        while (recMap.size > 0) {
                            const [fieldName, fieldMap] =
                                /** @type {[string, Map<Record, true>]} */ (
                                    recMap.entries().next().value
                                );
                            recMap.delete(fieldName);
                            const onDelete =
                                record.Model._.fieldsOnDelete.get(fieldName);
                            for (const removedRec of fieldMap.keys()) {
                                try {
                                    onDelete?.call(record._proxy, removedRec._proxy);
                                } catch (err) {
                                    this.handleError(err);
                                }
                            }
                        }
                    }
                    while (FU_QUEUE.size > 0) {
                        const [record, map] =
                            /** @type {[Record, Map<string, true>]} */ (
                                FU_QUEUE.entries().next().value
                            );
                        FU_QUEUE.delete(record);
                        for (const fieldName of map.keys()) {
                            record._.onUpdate(record, fieldName);
                        }
                    }
                    while (RO_QUEUE.size > 0) {
                        /** @type {Function} */
                        const cb = RO_QUEUE.keys().next().value;
                        RO_QUEUE.delete(cb);
                        try {
                            cb();
                        } catch (err) {
                            this.handleError(err);
                        }
                    }
                    while (RD_QUEUE.size > 0) {
                        /** @type {Record} */
                        const record = RD_QUEUE.keys().next().value;
                        RD_QUEUE.delete(record);
                        for (const [
                            usingRecord,
                            names,
                        ] of record._.uses.data.entries()) {
                            const aliveProxy = toRaw(this.recordByLocalId).get(
                                usingRecord.localId,
                            );
                            const alive =
                                (aliveProxy &&
                                    toRaw(aliveProxy)._raw === usingRecord) ||
                                deletingRecordsByLocalId.get(usingRecord.localId) ===
                                    usingRecord;
                            if (!alive) {
                                record._.uses.data.delete(usingRecord);
                                continue;
                            }
                            for (const [name2, count] of names.entries()) {
                                for (let c = 0; c < count; c++) {
                                    /** @type {RecordFields} */ (
                                        /** @type {unknown} */ (usingRecord)
                                    )[name2].delete(record);
                                }
                            }
                        }
                        for (const fieldName of record.Model._.fields.keys()) {
                            if (!isRelation(record.Model, fieldName)) {
                                continue;
                            }
                            const reclist = /** @type {RecordFields} */ (
                                /** @type {unknown} */ (record)
                            )[fieldName];
                            for (const localId of reclist.data) {
                                const targetProxy = toRaw(this.recordByLocalId).get(
                                    localId,
                                );
                                const target = targetProxy
                                    ? toRaw(targetProxy)._raw
                                    : deletingRecordsByLocalId.get(localId);
                                target?._.uses.delete(reclist);
                            }
                        }
                        deletingRecordsByLocalId.set(record.localId, record);
                        this.recordByLocalId.delete(record.localId);
                        record._proxy[IS_DELETED_SYM] = true;
                        delete record.Model.records[record.localId];
                        this._.ADD_QUEUE("hard_delete", record);
                    }
                    while (RHD_QUEUE.size > 0) {
                        /** @type {Record} */
                        const record = RHD_QUEUE.keys().next().value;
                        RHD_QUEUE.delete(record);
                        deletingRecordsByLocalId.delete(record.localId);
                    }
                }
            } finally {
                this._.UPDATE--;
            }
            if (this._.ERRORS.length) {
                if (this.warnErrors) {
                    console.warn("Store data insert aborted due to following errors:");
                    for (const err of this._.ERRORS) {
                        console.warn(err);
                    }
                }
                const [error1] = this._.ERRORS;
                this._.ERRORS = [];
                throw error1;
            }
        }
        return res;
    }
    /**
     * @param {Object} [dataByModelName={}]
     * @param {Object} [options={}]
     * @returns {void}
     */
    insert(dataByModelName = {}, options = {}) {
        const store = this;
        const rawStore = toRaw(this)._raw;
        const ctx = store._makeInsertContext();
        rawStore.MAKE_UPDATE(function storeInsert() {
            const recordsDataToDelete = [];
            for (const [pyOrJsModelName, data] of Object.entries(dataByModelName)) {
                const modelName = store._insertModelName(ctx, pyOrJsModelName);
                const models = /** @type {StoreModels} */ (
                    /** @type {unknown} */ (store)
                );
                if (!models[modelName]) {
                    console.warn(
                        `store.insert() received data for unknown model “${modelName}”.`,
                    );
                    continue;
                }
                const extraFields = store._insertExtraFields(pyOrJsModelName);
                const insertData = [];
                for (let vals of Array.isArray(data) ? data : [data]) {
                    if (extraFields) {
                        vals = { ...vals, ...extraFields };
                    }
                    if (vals._DELETE) {
                        if (!extraFields) {
                            vals = { ...vals };
                        }
                        delete vals._DELETE;
                        recordsDataToDelete.push([modelName, vals]);
                    } else {
                        insertData.push(vals);
                    }
                }
                models[modelName].insert(insertData, options);
            }
            for (const [modelName, vals] of recordsDataToDelete) {
                store[modelName].get(vals)?.delete();
            }
        });
    }
    /**
     * @param {Record} record
     * @param {string|string[]} name
     * @param {() => void} cb
     * @returns {() => void}
     */
    onChange(record, name, cb) {
        return this._onChange(record, name, (/** @type {() => void} */ observe) => {
            const fn = () => {
                observe();
                try {
                    cb();
                } catch (err) {
                    this.handleError(err);
                }
            };
            if (this._.UPDATE !== 0) {
                this._.RO_QUEUE.set(fn, true);
            } else {
                fn();
            }
        });
    }
    /**
     * @param {Record} record
     * @param {string|string[]} key
     * @param {(observe: Function) => any} callback
     * @returns {function}
     */
    _onChange(record, key, callback) {
        /** @type {RecordFields} */
        let proxy;
        function _observe() {
            const val = proxy[key];
            if (typeof val === "object" && val !== null) {
                void Object.keys(val);
            }
            if (Array.isArray(val)) {
                void val.length;
                void toRaw(val).forEach.call(val, (i) => i);
            }
        }
        if (Array.isArray(key)) {
            const disposers = key.map((k) => this._onChange(record, k, callback));
            return () => {
                for (const dispose of disposers) {
                    dispose();
                }
            };
        }
        let ready = true;
        proxy = reactive(record, () => {
            if (ready) {
                callback(_observe);
            }
        });
        _observe();
        return () => {
            ready = false;
            proxy = undefined;
            record = undefined;
            callback = undefined;
        };
    }
    /** @param {Object} data */
    _cleanupData(data) {
        super._cleanupData(data);
        if (this._getActualModelName() === "Store") {
            delete data.Models;
            for (const [name] of modelRegistry.getEntries()) {
                delete data[name];
            }
        }
    }
}
