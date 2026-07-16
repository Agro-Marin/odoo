/** @odoo-module native */
/**
 * Model layer overview.
 *
 * Every record and record list exists as a triad of objects:
 * - `_raw`: the plain instance. Fields hold raw values (relations hold raw
 *   `RecordList`s whose `data` is an array of localIds). Internal code works
 *   on `_raw` to avoid reactivity costs and re-entrancy.
 * - `_proxyInternal`: a `Proxy` over `_raw` implementing field semantics
 *   (relation get/set, commands). It is NOT an
 *   OWL reactive: reading through it does not subscribe an observer, but
 *   writing through it still notifies observers of `_proxy`.
 * - `_proxy`: `reactive(_proxyInternal)`, the object handed to business code
 *   and components. Reads through it (or through a `reactive()` wrapper of
 *   it) subscribe; getters "downgrade" a `_proxy` receiver to
 *   `_proxyInternal` so internal reads stay subscription-free.
 *
 * All mutations funnel through `Store.MAKE_UPDATE`, which counts nesting
 * depth (`UPDATE`) and defers side effects into queues. When the outermost
 * update ends, queues are flushed in a fixed order, repeated until all are
 * empty:
 *   FC (field computes) → FS (field sorts) → FA (field onAdd hooks)
 *   → FD (field onDelete hooks) → FU (field onUpdate hooks)
 *   → RO (record onChange observers) → RD (record deletes)
 *   → RHD (record hard-deletes).
 * Computed and sorted fields are always eager: they (re)run through the
 * FC/FS queues at record creation and whenever a dependency changes,
 * whether or not anything observes the field.
 * RD unregisters the record from `recordByLocalId` and `Model.records` and
 * detaches all relations; the record stays addressable through the local
 * `deletingRecordsByLocalId` map until RHD, so cleanups of the same flush
 * can still reference it.
 */
import { reactive, toRaw } from "@odoo/owl";

import { IS_DELETED_SYM, isRelation, modelRegistry, STORE_SYM } from "./misc.js";
import { Record } from "./record.js";

/** @typedef {import("./record_list").RecordList} RecordList */

export const storeInsertFns = {
    makeContext(store) {},
    getActualModelName(store, ctx, pyOrJsModelName) {
        return pyOrJsModelName;
    },
    getExtraFieldsFromModel(store) {},
};

export class Store extends Record {
    /** @type {import("./store_internal").StoreInternal} */
    _;
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

    handleError(err) {
        if (this._.UPDATE === 0) {
            // No update cycle is running to drain the queue (computes, sorts
            // and onChange callbacks triggered by a direct assignment execute
            // AFTER the assignment's own flush — OWL notifies observers after
            // Reflect.set returns). Parking the error here left it for the
            // NEXT unrelated MAKE_UPDATE to throw at an innocent caller,
            // masking that cycle's own failures. Report it now instead.
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
                // A nested update must not swallow: its caller would continue
                // on half-applied state. Depth 0 collects and rethrows below.
                throw err;
            }
            this.handleError(err);
        } finally {
            this._.UPDATE--;
        }
        if (this._.UPDATE === 0) {
            // Only the outermost (flushing) call needs this map; MAKE_UPDATE is
            // the hottest function in the layer and most calls are nested, so
            // allocating it here rather than per-call avoids a throwaway Map on
            // every field write.
            const deletingRecordsByLocalId = new Map();
            // pretend an increased update cycle so that nothing in queue creates many small update cycles
            this._.UPDATE++;
            // The finally below is load-bearing: if any flush step throws, the
            // UPDATE counter must still return to 0 — otherwise every later
            // update queues computes/hooks that are never flushed again and
            // the whole store is silently wedged for the rest of the session.
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
                        // mutually-retriggering computes/hooks: abort instead of
                        // livelocking the tab.
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
                        /** @type {[Record, Map<string, true>]} */
                        const [record, recMap] = FC_QUEUE.entries().next().value;
                        FC_QUEUE.delete(record);
                        for (const fieldName of recMap.keys()) {
                            record._.requestCompute(record, fieldName, { force: true });
                        }
                    }
                    while (FS_QUEUE.size > 0) {
                        /** @type {[Record, Map<string, true>]} */
                        const [record, recMap] = FS_QUEUE.entries().next().value;
                        FS_QUEUE.delete(record);
                        for (const fieldName of recMap.keys()) {
                            record._.requestSort(record, fieldName, { force: true });
                        }
                    }
                    while (FA_QUEUE.size > 0) {
                        /** @type {[Record, Map<string, Map<Record, true>>]} */
                        const [record, recMap] = FA_QUEUE.entries().next().value;
                        FA_QUEUE.delete(record);
                        while (recMap.size > 0) {
                            /** @type {[string, Map<Record, true>]} */
                            const [fieldName, fieldMap] = recMap.entries().next().value;
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
                        /** @type {[Record, Map<string, Map<Record, true>>]} */
                        const [record, recMap] = FD_QUEUE.entries().next().value;
                        FD_QUEUE.delete(record);
                        while (recMap.size > 0) {
                            /** @type {[string, Map<Record, true>]} */
                            const [fieldName, fieldMap] = recMap.entries().next().value;
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
                        /** @type {[Record, Map<string, true>]} */
                        const [record, map] = FU_QUEUE.entries().next().value;
                        FU_QUEUE.delete(record);
                        for (const fieldName of map.keys()) {
                            record._.onUpdate(record, fieldName);
                        }
                    }
                    while (RO_QUEUE.size > 0) {
                        /** @type {Map<Function, true>} */
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
                        // detach from every record that uses this record
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
                                // using record already hard-deleted, clean inverses
                                record._.uses.data.delete(usingRecord);
                                continue;
                            }
                            for (const [name2, count] of names.entries()) {
                                for (let c = 0; c < count; c++) {
                                    usingRecord[name2].delete(record);
                                }
                            }
                        }
                        // detach outgoing relations: without an inverse, the
                        // targets' `uses` would keep a stale entry forever
                        for (const fieldName of record.Model._.fields.keys()) {
                            if (!isRelation(record.Model, fieldName)) {
                                continue;
                            }
                            const reclist = record[fieldName];
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
                        // Two-registry invariant: recordByLocalId and
                        // Model.records are unregistered in the same step, so
                        // business code can no longer reach the record, while
                        // deletingRecordsByLocalId/RHD_QUEUE keep it
                        // addressable for the rest of this flush.
                        deletingRecordsByLocalId.set(record.localId, record);
                        this.recordByLocalId.delete(record.localId);
                        record._proxy[IS_DELETED_SYM] = true;
                        delete record.Model.records[record.localId];
                        this._.ADD_QUEUE("hard_delete", record);
                    }
                    while (RHD_QUEUE.size > 0) {
                        // effectively delete the record
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
     * @param {Object} [dataByModelName={}] data to insert, keyed by model name
     * @param {Object} [options={}]
     * @returns {void}
     */
    insert(dataByModelName = {}, options = {}) {
        const store = this;
        // batch on this store's own update cycle, not on the last-created
        // store (`Record.store`), so concurrent stores don't share queues
        const rawStore = toRaw(this)._raw;
        const ctx = storeInsertFns.makeContext(store);
        rawStore.MAKE_UPDATE(function storeInsert() {
            const recordsDataToDelete = [];
            for (const [pyOrJsModelName, data] of Object.entries(dataByModelName)) {
                const modelName = storeInsertFns.getActualModelName(
                    store,
                    ctx,
                    pyOrJsModelName,
                );
                if (!store[modelName]) {
                    console.warn(
                        `store.insert() received data for unknown model “${modelName}”.`,
                    );
                    continue;
                }
                const insertData = [];
                for (let vals of Array.isArray(data) ? data : [data]) {
                    const extraFields = storeInsertFns.getExtraFieldsFromModel(
                        store,
                        pyOrJsModelName,
                    );
                    // never mutate caller payloads: they may be reused
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
                store[modelName].insert(insertData, options);
            }
            // Delete after all inserts to make sure a relation potentially registered before the
            // delete doesn't re-add the deleted record by mistake.
            for (const [modelName, vals] of recordsDataToDelete) {
                store[modelName].get(vals)?.delete();
            }
        });
    }
    onChange(record, name, cb) {
        return this._onChange(record, name, (observe) => {
            const fn = () => {
                observe();
                try {
                    cb();
                } catch (err) {
                    this.handleError(err);
                }
            };
            if (this._.UPDATE !== 0) {
                // `fn` is a fresh closure each call, so it is always new to the
                // queue; enqueue it directly (dedup here would be a no-op).
                this._.RO_QUEUE.set(fn, true);
            } else {
                fn();
            }
        });
    }
    /**
     * Version of onChange where the callback receives observe function as param.
     * This is useful when there's desire to postpone calling the callback function,
     * in which the observe is also intended to have its invocation postponed.
     *
     * @param {Record} record
     * @param {string|string[]} key
     * @param {(observe: Function) => any} callback
     * @returns {function} function to call to stop observing changes
     */
    _onChange(record, key, callback) {
        let proxy;
        function _observe() {
            // access proxy[key] only once to avoid triggering reactive get() many times
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
        };
    }
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
