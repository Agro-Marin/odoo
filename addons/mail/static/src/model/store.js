// @ts-check
/** @odoo-module native */
import { reactive, toRaw } from "@odoo/owl";

import { IS_DELETED_SYM, isRelation, modelRegistry, STORE_SYM } from "./misc.js";
import { Record } from "./record.js";

/** @import { RecordList } from "./record_list" */
/** @import { RecordData } from "./record" */
/** @import { RecordFields } from "./record" */
/** @import { StoreModels } from "./record" */
/** @import { StoreInternal } from "./store_internal" */

/**
 * @param {Object} target
 * @param {string|string[]} key
 * @param {(observe: () => void) => any} callback
 * @returns {() => void}
 */
export function observeKey(target, key, callback) {
    if (Array.isArray(key)) {
        const disposers = key.map((k) => observeKey(target, k, callback));
        return () => {
            for (const dispose of disposers) {
                dispose();
            }
        };
    }
    /** @type {{proxy?: object, target?: object, callback?: (observe: () => void) => unknown}} */
    const subscription = { target, callback };
    function observe() {
        const val = /** @type {Object<string, unknown> | undefined} */ (
            subscription.proxy
        )?.[/** @type {string} */ (key)];
        if (typeof val === "object" && val !== null) {
            void Object.keys(val);
        }
        if (Array.isArray(val)) {
            void val.length;
            void toRaw(val).forEach.call(val, (i) => i);
        }
    }
    let ready = true;
    subscription.proxy = reactive(target, () => {
        if (ready) {
            subscription.callback?.(observe);
        }
    });
    observe();
    return () => {
        ready = false;
        subscription.proxy = undefined;
        subscription.target = undefined;
        subscription.callback = undefined;
    };
}
export class Store extends Record {
    /** @type {StoreModels} */
    Models;
    /** @returns {any|void} */
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

    [STORE_SYM] = true;
    /** @type {Map<string, Record>} */
    recordByLocalId;
    storeReady = false;
    /**
     * @param {string} localId
     * @returns {Record | undefined}
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
            if (this.logErrors) {
                console.warn(err);
            }
            throw err;
        }
        this._.ERRORS.push(err);
    }

    /** @type {boolean} */
    logErrors = true;

    /** @param {StoreInternal["FC_QUEUE"]} FC_QUEUE */
    _drainForcedComputes(FC_QUEUE) {
        while (FC_QUEUE.size > 0) {
            const [record, recMap] = /** @type {[Record, Map<string, true>]} */ (
                FC_QUEUE.entries().next().value
            );
            FC_QUEUE.delete(record);
            for (const fieldName of recMap.keys()) {
                record._.requestCompute(record, fieldName, { force: true });
            }
        }
    }
    /** @param {StoreInternal["FS_QUEUE"]} FS_QUEUE */
    _drainForcedSorts(FS_QUEUE) {
        while (FS_QUEUE.size > 0) {
            const [record, recMap] = /** @type {[Record, Map<string, true>]} */ (
                FS_QUEUE.entries().next().value
            );
            FS_QUEUE.delete(record);
            for (const fieldName of recMap.keys()) {
                record._.requestSort(record, fieldName, { force: true });
            }
        }
    }
    /** @param {StoreInternal["FA_QUEUE"]} FA_QUEUE */
    _drainOnAdd(FA_QUEUE) {
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
    }
    /** @param {StoreInternal["FD_QUEUE"]} FD_QUEUE */
    _drainOnDelete(FD_QUEUE) {
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
                const onDelete = record.Model._.fieldsOnDelete.get(fieldName);
                for (const removedRec of fieldMap.keys()) {
                    try {
                        onDelete?.call(record._proxy, removedRec._proxy);
                    } catch (err) {
                        this.handleError(err);
                    }
                }
            }
        }
    }
    /** @param {StoreInternal["FU_QUEUE"]} FU_QUEUE */
    _drainOnUpdate(FU_QUEUE) {
        while (FU_QUEUE.size > 0) {
            const [record, map] = /** @type {[Record, Map<string, true>]} */ (
                FU_QUEUE.entries().next().value
            );
            FU_QUEUE.delete(record);
            for (const fieldName of map.keys()) {
                record._.onUpdate(record, fieldName);
            }
        }
    }
    /** @param {StoreInternal["RO_QUEUE"]} RO_QUEUE */
    _drainCallbacks(RO_QUEUE) {
        while (RO_QUEUE.size > 0) {
            const cb = RO_QUEUE.keys().next().value;
            if (cb === undefined) {
                break;
            }
            RO_QUEUE.delete(cb);
            try {
                cb();
            } catch (err) {
                this.handleError(err);
            }
        }
    }
    /**
     * @param {StoreInternal["RD_QUEUE"]} RD_QUEUE
     * @param {Map<string, Record>} deletingRecordsByLocalId
     */
    _drainDeletes(RD_QUEUE, deletingRecordsByLocalId) {
        while (RD_QUEUE.size > 0) {
            const record = RD_QUEUE.keys().next().value;
            if (record === undefined) {
                break;
            }
            RD_QUEUE.delete(record);
            for (const [usingRecord, names] of record._.uses.data.entries()) {
                const aliveProxy = toRaw(this.recordByLocalId).get(usingRecord.localId);
                const alive =
                    (aliveProxy && toRaw(aliveProxy)._raw === usingRecord) ||
                    deletingRecordsByLocalId.get(usingRecord.localId) === usingRecord;
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
                    const targetProxy = toRaw(this.recordByLocalId).get(localId);
                    const target = targetProxy
                        ? toRaw(targetProxy)._raw
                        : deletingRecordsByLocalId.get(localId);
                    target?._.uses.delete(reclist);
                }
            }
            deletingRecordsByLocalId.set(record.localId, record);
            this.recordByLocalId.delete(record.localId);
            /** @type {RecordFields} */ (/** @type {unknown} */ (record._proxy))[
                IS_DELETED_SYM
            ] = true;
            delete record.Model.records[record.localId];
            this._.ADD_QUEUE("hard_delete", record);
        }
    }
    /**
     * @param {StoreInternal["RHD_QUEUE"]} RHD_QUEUE
     * @param {Map<string, Record>} deletingRecordsByLocalId
     */
    _drainHardDeletes(RHD_QUEUE, deletingRecordsByLocalId) {
        while (RHD_QUEUE.size > 0) {
            const record = RHD_QUEUE.keys().next().value;
            if (record === undefined) {
                break;
            }
            RHD_QUEUE.delete(record);
            deletingRecordsByLocalId.delete(record.localId);
        }
    }
    /** @returns {boolean} */
    _hasQueuedWork() {
        return (
            this._.FC_QUEUE.size > 0 ||
            this._.FS_QUEUE.size > 0 ||
            this._.FA_QUEUE.size > 0 ||
            this._.FD_QUEUE.size > 0 ||
            this._.FU_QUEUE.size > 0 ||
            this._.RO_QUEUE.size > 0 ||
            this._.RD_QUEUE.size > 0 ||
            this._.RHD_QUEUE.size > 0
        );
    }
    /** @param {Map<string, Record>} deletingRecordsByLocalId */
    _drainQueuesOnce(deletingRecordsByLocalId) {
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
        this._drainForcedComputes(FC_QUEUE);
        this._drainForcedSorts(FS_QUEUE);
        this._drainOnAdd(FA_QUEUE);
        this._drainOnDelete(FD_QUEUE);
        this._drainOnUpdate(FU_QUEUE);
        this._drainCallbacks(RO_QUEUE);
        this._drainDeletes(RD_QUEUE, deletingRecordsByLocalId);
        this._drainHardDeletes(RHD_QUEUE, deletingRecordsByLocalId);
    }
    _flushQueues() {
        const deletingRecordsByLocalId = new Map();
        this._.UPDATE++;
        let flushIterations = 0;
        try {
            while (this._hasQueuedWork()) {
                if (++flushIterations > 1000) {
                    this.handleError(
                        new Error("Store flush did not converge (1000 iterations)"),
                    );
                    break;
                }
                this._drainQueuesOnce(deletingRecordsByLocalId);
            }
        } finally {
            this._.UPDATE--;
        }
    }
    _throwFirstQueuedError() {
        if (!this._.ERRORS.length) {
            return;
        }
        if (this.logErrors) {
            console.warn("Store data insert aborted due to following errors:");
            for (const err of this._.ERRORS) {
                console.warn(err);
            }
        }
        const [error1] = this._.ERRORS;
        this._.ERRORS = [];
        throw error1;
    }
    /**
     * @template T
     * @param {() => T} fn
     * @returns {T}
     */
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
            this._flushQueues();
            this._throwFirstQueuedError();
        }
        // A failed callback is rethrown above, after queued updates are flushed.
        return /** @type {T} */ (res);
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
            /** @type {Map<string|number, [string, RecordData]>} */
            const recordsDataToDelete = new Map();
            let unresolvedIdentity = 0;
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
                    let identity;
                    try {
                        identity = `${modelName}:${models[modelName].localId(vals)}`;
                    } catch {
                        identity = ++unresolvedIdentity;
                    }
                    if (vals._DELETE) {
                        if (!extraFields) {
                            vals = { ...vals };
                        }
                        delete vals._DELETE;
                        recordsDataToDelete.set(identity, [modelName, vals]);
                    } else {
                        recordsDataToDelete.delete(identity);
                        insertData.push(vals);
                    }
                }
                try {
                    models[modelName].insert(insertData, options);
                } catch (error) {
                    rawStore.handleError(error);
                }
            }
            for (const [modelName, vals] of recordsDataToDelete.values()) {
                /** @type {StoreModels} */ (/** @type {unknown} */ (store))[modelName]
                    .get(vals)
                    ?.delete();
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
     * @param {(observe: () => void) => any} callback
     * @returns {() => void}
     */
    _onChange(record, key, callback) {
        return observeKey(record, key, callback);
    }
    /** @param {RecordData} data */
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
