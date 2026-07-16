/** @odoo-module native */
import { markRaw, reactive, toRaw } from "@odoo/owl";

import { isRecord } from "./misc.js";

/** @param {RecordList} reclist */
function getInverse(reclist) {
    return reclist._.owner.Model._.fieldsInverse.get(reclist._.name);
}

/** @param {RecordList} reclist */
function getTargetModel(reclist) {
    return reclist._.owner.Model._.fieldsTargetModel.get(reclist._.name);
}

/** @param {RecordList} reclist */
function isOne(reclist) {
    return reclist._.owner.Model._.fieldsOne.get(reclist._.name);
}

export class RecordListInternal {
    /** @type {string} */
    name;
    /** @type {Record} */
    owner;

    /**
     * Version of add() that does not update the inverse.
     * This is internally called when inserting (with intent to add)
     * on relational field with inverse, to prevent infinite loops.
     *
     * @param {RecordList} recordList
     * @param {...Record}
     */
    addNoinv(recordList, ...records) {
        const self = this;
        const store = recordList._store;
        if (isOne(recordList)) {
            const last = records.at(-1);
            if (isRecord(last) && last.in(recordList)) {
                return;
            }
            let changed = false;
            const record = self.insert(
                recordList,
                last,
                function recordList_AddNoInvOneInsert(record) {
                    if (record.localId !== recordList.data[0]) {
                        changed = true;
                        const old = recordList._proxy.at(-1);
                        recordList._proxy.data.pop();
                        old?._.uses.delete(recordList);
                        recordList._proxy.data.push(record.localId);
                        self.syncLength(recordList);
                        record._.uses.add(recordList);
                        if (old) {
                            // re-parenting through the many side: detach from
                            // the old owner's inverse list and fire onDelete,
                            // as a direct one-side write would
                            const oldRecord = toRaw(old)._raw;
                            store._.ADD_QUEUE(
                                "onDelete",
                                self.owner,
                                self.name,
                                oldRecord,
                            );
                            const inverse = getInverse(recordList);
                            // computed inverses are excluded: their compute
                            // re-asserts the value right after the eviction,
                            // and two computes claiming the same exclusive One
                            // slot would evict each other in an endless flush
                            // cycle (e.g. channel members racing for
                            // thread.self_member_id via threadAsSelf)
                            if (
                                inverse &&
                                !oldRecord.Model._.fieldsCompute.get(inverse)
                            ) {
                                oldRecord[inverse].delete(self.owner);
                            }
                        }
                    }
                },
                { inv: false },
            );
            if (changed) {
                // only on actual membership change: a spurious onAdd would
                // schedule sorts and fire hooks for a no-op write
                store._.ADD_QUEUE("onAdd", self.owner, self.name, record);
            }
            return;
        }
        for (const val of records) {
            if (isRecord(val) && val.in(recordList)) {
                continue;
            }
            let added = false;
            const record = self.insert(
                recordList,
                val,
                function recordList_AddNoInvManyInsert(record) {
                    if (recordList.data.indexOf(record.localId) === -1) {
                        recordList._proxy.data.push(record.localId);
                        self.syncLength(recordList);
                        record._.uses.add(recordList);
                        added = true;
                    }
                },
                { inv: false },
            );
            if (added) {
                store._.ADD_QUEUE("onAdd", self.owner, self.name, record);
            }
        }
    }
    /** @param {R[]|any[]} data */
    assign(recordList, data) {
        const self = this;
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListAssign() {
            /** @type {Record[]|Set<Record>|RecordList<Record|any[]>} */
            const collection = isRecord(data) ? [data] : data;
            // data and collection could be same record list,
            // save before clear to not push mutated recordlist that is empty
            const vals = [...collection].filter(
                (val) => val !== undefined && val !== null && val !== false,
            );
            const oldRecords = recordList._proxyInternal.slice
                .call(recordList._proxy)
                .map((recordProxy) => toRaw(recordProxy)._raw);
            // Membership via localId Sets so reassigning a large relation is
            // O(n), not O(n²) (mirrors the Set-based fast path in add()).
            // Records held by a RecordList always carry a localId.
            const oldLocalIdSet = new Set(oldRecords.map((record) => record.localId));
            // dedupe while mapping (add() dedupes, assign() didn't): a
            // payload containing the same record twice put duplicate
            // localIds in data, double-counted uses, and a later delete()
            // removed one occurrence while fully unlinking the inverse —
            // bidirectional state diverged
            const newLocalIdSet = new Set();
            const newRecords = [];
            for (const val of vals) {
                const record = self.insert(
                    recordList,
                    val,
                    function recordListAssignInsert(record) {
                        if (
                            !oldLocalIdSet.has(record.localId) &&
                            !newLocalIdSet.has(record.localId)
                        ) {
                            record._.uses.add(recordList);
                            store._.ADD_QUEUE("onAdd", self.owner, self.name, record);
                        }
                    },
                );
                if (!record || newLocalIdSet.has(record.localId)) {
                    continue;
                }
                newLocalIdSet.add(record.localId);
                newRecords.push(record);
            }
            const inverse = getInverse(recordList);
            for (const oldRecord of oldRecords) {
                if (!newLocalIdSet.has(oldRecord.localId)) {
                    oldRecord._.uses.delete(recordList);
                    store._.ADD_QUEUE("onDelete", self.owner, self.name, oldRecord);
                    if (inverse) {
                        oldRecord[inverse].delete(self.owner);
                    }
                }
            }
            const newLocalIds = newRecords.map((newRecord) => newRecord.localId);
            // diff before writing: a fresh array would invalidate every
            // observer even when membership and order are identical
            const hasChanged =
                newLocalIds.length !== recordList.data.length ||
                recordList.data.some((localId, i) => localId !== newLocalIds[i]);
            if (hasChanged) {
                recordList._proxy.data = newLocalIds;
                recordList._.syncLength(recordList);
            }
        });
    }
    /**
     * Version of delete() that does not update the inverse.
     * This is internally called when inserting (with intent to delete)
     * on relational field with inverse, to prevent infinite loops.
     *
     * @param {RecordList} recordList
     * @param {...Record}
     */
    deleteNoinv(recordList, ...records) {
        const self = this;
        const store = recordList._store;
        for (const val of records) {
            let removed = false;
            const record = this.insert(
                recordList,
                val,
                function recordList_DeleteNoInv_Insert(record) {
                    const index = recordList.data.indexOf(record.localId);
                    if (index !== -1) {
                        recordList.splice.call(recordList._proxy, index, 1);
                        self.syncLength(recordList);
                        removed = true;
                    }
                },
                { inv: false },
            );
            if (removed) {
                // only on actual membership change: this path runs for EVERY
                // delete(x) via the inverse command, including when x was not
                // in the relation — a spurious onDelete would fire hooks
                // (e.g. (r) => r.delete()) with a record that was never there
                store._.ADD_QUEUE("onDelete", self.owner, self.name, record);
            }
        }
    }
    /**
     * The internal reactive is only necessary to trigger outer reactives when
     * writing on it. As it has no callback, reading through it has no effect,
     * except slowing down performance and complexifying the stack.
     *
     * @param {RecordList} recordList
     * @param {RecordList} fullProxy
     */
    downgradeProxy(recordList, fullProxy) {
        return recordList._proxy === fullProxy ? recordList._proxyInternal : fullProxy;
    }
    /**
     * @param {RecordList} recordList
     * @param {R|any} val
     * @param {(R) => void} [fn] function that is called in-between preinsert and
     *   insert. Preinsert only inserted what's needed to make record, while
     *   insert finalize with all remaining data.
     * @param {boolean} [inv=true] whether the inverse should be added or not.
     *   It is always added except when during an insert on a relational field,
     *   in order to avoid infinite loop.
     * @param {"ADD"|"DELETE} [mode="ADD"] the mode of insert on the relation.
     *   Important to match the inverse. Most of the time it's "ADD", that is when
     *   inserting the relation the inverse should be added. Exception when the insert
     *   comes from deletion, we want to "DELETE".
     */
    insert(recordList, val, fn, { inv = true, mode = "ADD" } = {}) {
        if (val === undefined || val === null || val === false) {
            // nullish entries materialized phantom records ("Model,undefined",
            // "Model,null") registered in the store forever. Whole-value
            // clears are handled upstream (updateRelationOne/Many): a nullish
            // ENTRY in a relation write is a no-op. Callers must tolerate the
            // undefined return.
            return undefined;
        }
        const inverse = getInverse(recordList);
        const targetModel = getTargetModel(recordList);
        if (typeof val !== "object") {
            if (Array.isArray(recordList._store[targetModel].id)) {
                throw new Error(
                    `Cannot insert "${val}" on relational field "${recordList._.owner.Model.getName()}/${
                        recordList._.name
                    }": target model "${targetModel}" doesn't support single-id data!`,
                );
            }
            // single-id data
            val = { [recordList._store[targetModel].id]: val };
        }
        if (inverse && inv) {
            // special command to call addNoinv/deleteNoInv, to prevent infinite loop
            const command = [
                [mode === "ADD" ? "ADD.noinv" : "DELETE.noinv", recordList._.owner],
            ];
            if (isRecord(val)) {
                const target = val._raw === val ? val._proxy : val;
                target[inverse] = command;
            } else {
                // `val` is a caller-supplied plain payload that may be reused for
                // later inserts; clone it instead of writing the inverse command
                // onto the original (see the no-mutate-payload policy in store.js).
                val = { ...val, [inverse]: command };
            }
        }
        /** @type {R} */
        let newRecordProxy;
        if (!isRecord(val)) {
            newRecordProxy = recordList._store[targetModel].preinsert(val);
        } else {
            newRecordProxy = val;
        }
        const newRecord = toRaw(newRecordProxy)._raw;
        fn?.(newRecord);
        if (!isRecord(val)) {
            // was preinserted, fully insert now
            recordList._store[targetModel].insert(val);
        }
        return newRecord;
    }
    /**
     * Sync reclist.data length with array length, as to not introduce confusion while debugging
     *
     * @param {RecordList} reclist
     */
    syncLength(reclist) {
        reclist.length = reclist.data.length;
    }
}

/** * @template {Record} R */
export class RecordList extends Array {
    /** @type {import("models").Store} */
    _store;
    /** @type {string[]} */
    data = [];
    /** @type {this} */
    _raw;
    /** @type {this} */
    _proxyInternal;
    /** @type {this} */
    _proxy;
    _ = markRaw(new RecordListInternal());

    constructor() {
        super();
        const recordList = this;
        recordList._raw = recordList;
        const recordListProxyInternal = new Proxy(recordList, {
            /** @param {RecordList<R>} receiver */
            get(recordList, name, recordListFullProxy) {
                recordListFullProxy = recordList._.downgradeProxy(
                    recordList,
                    recordListFullProxy,
                );
                if (
                    typeof name === "symbol" ||
                    // "length" is an own (non-enumerable) array property: it
                    // must fall through to the data-backed branch below
                    (name !== "length" &&
                        Object.prototype.hasOwnProperty.call(recordList, name)) ||
                    Object.prototype.hasOwnProperty.call(
                        recordList.constructor.prototype,
                        name,
                    )
                ) {
                    let res = Reflect.get(...arguments);
                    if (typeof res === "function") {
                        res = res.bind(recordListFullProxy);
                    }
                    return res;
                }
                if (name === "length") {
                    return recordListFullProxy.data.length;
                }
                if (typeof name !== "symbol" && !window.isNaN(parseInt(name))) {
                    // support for "array[index]" syntax
                    const index = parseInt(name);
                    return recordListFullProxy._store.recordByLocalId.get(
                        recordListFullProxy.data[index],
                    );
                }
                // Attempt an unimplemented array method call
                const array = [
                    ...recordList[Symbol.iterator].call(recordListFullProxy),
                ];
                return array[name]?.bind(array);
            },
            /** @param {RecordList<R>} recordListProxy */
            set(recordList, name, val, recordListProxy) {
                const store = recordList._store;
                return store.MAKE_UPDATE(function recordListSet() {
                    if (typeof name !== "symbol" && !window.isNaN(parseInt(name))) {
                        // support for "array[index] = r3" syntax
                        const index = parseInt(name);
                        if (index < 0 || index > recordList.data.length) {
                            throw new Error(
                                `Cannot assign index ${index} on record list "${recordList._.owner.Model.getName()}/${
                                    recordList._.name
                                }": out of range (length: ${recordList.data.length})`,
                            );
                        }
                        if (val === undefined || val === null || val === false) {
                            throw new Error(
                                `Cannot assign "${val}" at index ${index} on record list "${recordList._.owner.Model.getName()}/${
                                    recordList._.name
                                }": use delete()/splice() to remove records`,
                            );
                        }
                        recordList._.insert(
                            recordList,
                            val,
                            function recordListSet_Insert(newRecord) {
                                const oldLocalId = recordList.data[index];
                                const oldRecordProxy =
                                    oldLocalId &&
                                    toRaw(recordList._store.recordByLocalId).get(
                                        oldLocalId,
                                    );
                                const oldRecord = oldRecordProxy
                                    ? toRaw(oldRecordProxy)._raw
                                    : undefined;
                                if (oldRecord?.eq(newRecord)) {
                                    return; // self-assignment: no hooks, no inverse churn
                                }
                                recordListProxy.data[index] = newRecord?.localId;
                                recordList._.syncLength(recordList);
                                const inverse = getInverse(recordList);
                                if (oldRecord) {
                                    oldRecord._.uses.delete(recordList);
                                    store._.ADD_QUEUE(
                                        "onDelete",
                                        recordList._.owner,
                                        recordList._.name,
                                        oldRecord,
                                    );
                                    if (inverse) {
                                        oldRecord[inverse].delete(recordList._.owner);
                                    }
                                }
                                if (newRecord) {
                                    newRecord._.uses.add(recordList);
                                    store._.ADD_QUEUE(
                                        "onAdd",
                                        recordList._.owner,
                                        recordList._.name,
                                        newRecord,
                                    );
                                    if (inverse) {
                                        newRecord[inverse].add?.(recordList._.owner);
                                    }
                                }
                            },
                        );
                    } else if (name === "length") {
                        const newLength = parseInt(val);
                        if (newLength !== recordList.data.length) {
                            if (newLength < recordList.data.length) {
                                recordList.splice.call(
                                    recordListProxy,
                                    newLength,
                                    recordList.length - newLength,
                                );
                            }
                            recordListProxy.data.length = newLength;
                            recordList._.syncLength(recordList);
                        }
                    } else {
                        return Reflect.set(recordList, name, val, recordListProxy);
                    }
                    return true;
                });
            },
        });
        recordList._proxyInternal = recordListProxyInternal;
        recordList._proxy = reactive(recordListProxyInternal);
        return recordList;
    }
    /** @param {R[]} records */
    push(...records) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListPush() {
            for (const val of records) {
                const record = recordList._.insert(
                    recordList,
                    val,
                    function recordListPushInsert(record) {
                        recordList._proxy.data.push(record.localId);
                        recordList._.syncLength(recordList);
                        record._.uses.add(recordList);
                    },
                );
                store._.ADD_QUEUE(
                    "onAdd",
                    recordList._.owner,
                    recordList._.name,
                    record,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    record[inverse].add(recordList._.owner);
                }
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @returns {R} */
    pop() {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListPop() {
            /** @type {R} */
            const oldRecordProxy = recordListFullProxy.at(-1);
            if (oldRecordProxy) {
                recordList.splice.call(
                    recordListFullProxy,
                    recordListFullProxy.length - 1,
                    1,
                );
            }
            return oldRecordProxy;
        });
    }
    /** @returns {R} */
    shift() {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListShift() {
            // mutate through _proxy (like push/splice): mutating the possibly
            // downgraded full proxy's data skips OWL reactivity notifications.
            const recordProxy = recordListFullProxy._store.recordByLocalId.get(
                recordList._proxy.data.shift(),
            );
            recordList._.syncLength(recordList);
            if (!recordProxy) {
                return;
            }
            const record = toRaw(recordProxy)._raw;
            record._.uses.delete(recordList);
            store._.ADD_QUEUE(
                "onDelete",
                recordList._.owner,
                recordList._.name,
                record,
            );
            const inverse = getInverse(recordList);
            if (inverse) {
                record[inverse].delete(recordList._.owner);
            }
            return recordProxy;
        });
    }
    /** @param {R[]} records */
    unshift(...records) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListUnshift() {
            for (let i = records.length - 1; i >= 0; i--) {
                const record = recordList._.insert(recordList, records[i], (record) => {
                    recordList._proxy.data.unshift(record.localId);
                    recordList._.syncLength(recordList);
                    record._.uses.add(recordList);
                });
                store._.ADD_QUEUE(
                    "onAdd",
                    recordList._.owner,
                    recordList._.name,
                    record,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    record[inverse].add(recordList._.owner);
                }
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @param {R} recordProxy */
    indexOf(recordProxy) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        return recordListFullProxy.data.indexOf(toRaw(recordProxy)?._raw.localId);
    }
    /**
     * @param {number} [start]
     * @param {number} [deleteCount]
     * @param {...R} [newRecordsProxy]
     */
    splice(start, deleteCount, ...newRecordsProxy) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        if (deleteCount === undefined) {
            // Array.prototype.splice(start) removes to the end; the
            // undefined count silently removed NOTHING here (NaN slice)
            deleteCount = recordList.data.length - start;
        }
        return store.MAKE_UPDATE(function recordListSplice() {
            const oldRecordLocalIds = recordList.data.slice(start, start + deleteCount);
            const oldRecords = oldRecordLocalIds.map(
                (localId) =>
                    toRaw(toRaw(recordList._store.recordByLocalId).get(localId))._raw,
            );
            const list = recordListFullProxy.data.slice(); // splice on copy of list so that reactive observers not triggered while splicing
            list.splice(
                start,
                deleteCount,
                ...newRecordsProxy.map(
                    (newRecordProxy) => toRaw(newRecordProxy)._raw.localId,
                ),
            );
            if (isOne(recordList) && start === 0 && deleteCount === 1) {
                // avoid replacing whole list, to avoid triggering observers too much
                if (list.length === 0) {
                    recordList._proxy.data.pop();
                } else {
                    recordList._proxy.data[0] = list[0];
                }
            } else {
                recordList._proxy.data = list;
            }
            recordList._.syncLength(recordList);
            for (const oldRecord of oldRecords) {
                oldRecord._.uses.delete(recordList);
                store._.ADD_QUEUE(
                    "onDelete",
                    recordList._.owner,
                    recordList._.name,
                    oldRecord,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    oldRecord[inverse].delete(recordList._.owner);
                }
            }
            for (const newRecordProxy of newRecordsProxy) {
                const newRecord = toRaw(newRecordProxy)._raw;
                newRecord._.uses.add(recordList);
                store._.ADD_QUEUE(
                    "onAdd",
                    recordList._.owner,
                    recordList._.name,
                    newRecord,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    newRecord[inverse].add(recordList._.owner);
                }
            }
        });
    }
    /** @param {(a: R, b: R) => boolean} func */
    sort(func) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListSort() {
            recordList._store._.sortRecordList(recordListFullProxy, func);
            return recordListFullProxy;
        });
    }
    /** @param {...R[]|...RecordList[R]} collections */
    concat(...collections) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        return recordListFullProxy.data
            .map((localId) => recordListFullProxy._store.recordByLocalId.get(localId))
            .concat(...collections.map((c) => [...c]));
    }
    /**
     * @param {...R}
     * @returns {R|R[]} the added record(s)
     */
    add(...records) {
        const recordList = toRaw(this)._raw;
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListAdd() {
            if (isOne(recordList)) {
                const last = records.at(-1);
                if (
                    isRecord(last) &&
                    recordList.data.includes(toRaw(last)._raw.localId)
                ) {
                    return last;
                }
                return recordList._.insert(
                    recordList,
                    last,
                    function recordListAddInsertOne(record) {
                        if (record.localId !== recordList.data[0]) {
                            recordList.splice.call(recordList._proxy, 0, 1, record);
                        }
                    },
                );
            }
            const res = [];
            // Set-based membership so that bulk adds are O(n), not O(n²)
            const known = records.length > 1 ? new Set(recordList.data) : null;
            const has = (localId) =>
                known ? known.has(localId) : recordList.data.includes(localId);
            for (const val of records) {
                if (isRecord(val) && has(toRaw(val)._raw.localId)) {
                    continue;
                }
                const rec = recordList._.insert(
                    recordList,
                    val,
                    function recordListAddInsertMany(record) {
                        if (!has(record.localId)) {
                            recordList.push.call(recordList._proxy, record);
                            known?.add(record.localId);
                        }
                    },
                );
                res.push(rec);
            }
            return res.length === 1 ? res[0] : res;
        });
    }
    /** @param {...R}  */
    delete(...records) {
        const recordList = toRaw(this)._raw;
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListDelete() {
            for (const val of records) {
                let target = val;
                if (val === undefined || val === null || val === false) {
                    continue;
                }
                if (!isRecord(val)) {
                    // resolve WITHOUT creating: a DELETE for a record the
                    // client never loaded (reachable in production via server
                    // ("DELETE", {...}) commands, e.g. deleting a reaction
                    // that was never fetched) used to fully insert a
                    // detached ghost record just to not-remove it
                    target = recordList._store[getTargetModel(recordList)].get(val);
                    if (!target) {
                        continue;
                    }
                }
                recordList._.insert(
                    recordList,
                    target,
                    function recordListDelete_Insert(record) {
                        const index = recordList.data.indexOf(record.localId);
                        if (index !== -1) {
                            recordList.splice.call(recordList._proxy, index, 1);
                        }
                    },
                    { mode: "DELETE" },
                );
            }
        });
    }
    clear() {
        const recordList = toRaw(this)._raw;
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListClear() {
            const oldLocalIds = recordList.data.slice();
            if (oldLocalIds.length === 0) {
                return;
            }
            // empty `data` in a single write (per-pop splicing is O(n²));
            // hooks are queued per record, in removal order (last first),
            // matching the historical pop-based behavior
            if (isOne(recordList)) {
                recordList._proxy.data.pop();
            } else {
                recordList._proxy.data = [];
            }
            recordList._.syncLength(recordList);
            const inverse = getInverse(recordList);
            for (let i = oldLocalIds.length - 1; i >= 0; i--) {
                const oldRecordProxy = toRaw(recordList._store.recordByLocalId).get(
                    oldLocalIds[i],
                );
                if (!oldRecordProxy) {
                    continue;
                }
                const oldRecord = toRaw(oldRecordProxy)._raw;
                oldRecord._.uses.delete(recordList);
                store._.ADD_QUEUE(
                    "onDelete",
                    recordList._.owner,
                    recordList._.name,
                    oldRecord,
                );
                if (inverse) {
                    oldRecord[inverse].delete(recordList._.owner);
                }
            }
        });
    }
    /** @yields {R} */
    *[Symbol.iterator]() {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        for (const localId of recordListFullProxy.data) {
            yield recordListFullProxy._store.recordByLocalId.get(localId);
        }
    }
    /** @param {number} index */
    at(index) {
        // this custom implement of "at" is slightly faster than auto-calling unimplement array method
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        return recordListFullProxy._store.recordByLocalId.get(
            recordListFullProxy.data.at(index),
        );
    }
    /**
     * Read-only Array methods below are implemented directly over `data`
     * (no full-array materialization per call).
     */
    /** @param {(record: R, index: number) => any} fn */
    map(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        return recordListFullProxy.data.map((localId, index) =>
            fn(recordByLocalId.get(localId), index, this),
        );
    }
    /**
     * @param {(record: R, index: number) => boolean} fn
     * @returns {R[]}
     */
    filter(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const result = [];
        const data = recordListFullProxy.data;
        for (let index = 0; index < data.length; index++) {
            const recordProxy = recordByLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                result.push(recordProxy);
            }
        }
        return result;
    }
    /**
     * @param {(record: R, index: number) => boolean} fn
     * @returns {R|undefined}
     */
    find(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = 0; index < data.length; index++) {
            const recordProxy = recordByLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                return recordProxy;
            }
        }
        return undefined;
    }

    findLast(fn) {
        // direct reverse loop like find(): the generic fallthrough would
        // materialize a full proxy array per call, and findLast is on hot
        // paths (thread scroll bookkeeping reads the newest message)
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = data.length - 1; index >= 0; index--) {
            const recordProxy = recordByLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                return recordProxy;
            }
        }
        return undefined;
    }

    findLastIndex(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = data.length - 1; index >= 0; index--) {
            const recordProxy = recordByLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                return index;
            }
        }
        return -1;
    }
    /** @param {(record: R, index: number) => boolean} fn */
    findIndex(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = 0; index < data.length; index++) {
            if (fn(recordByLocalId.get(data[index]), index, this)) {
                return index;
            }
        }
        return -1;
    }
    /** @param {(record: R, index: number) => boolean} fn */
    some(fn) {
        return this.findIndex(fn) !== -1;
    }
    /** @param {(record: R, index: number) => boolean} fn */
    every(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = 0; index < data.length; index++) {
            if (!fn(recordByLocalId.get(data[index]), index, this)) {
                return false;
            }
        }
        return true;
    }
    /** @param {(record: R, index: number) => void} fn */
    forEach(fn) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        for (let index = 0; index < data.length; index++) {
            fn(recordByLocalId.get(data[index]), index, this);
        }
    }
    /** @param {(acc: any, record: R, index: number) => any} fn */
    reduce(fn, ...init) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const data = recordListFullProxy.data;
        let acc;
        let start = 0;
        if (init.length) {
            acc = init[0];
        } else {
            if (data.length === 0) {
                throw new TypeError(
                    "Reduce of empty record list with no initial value",
                );
            }
            acc = recordByLocalId.get(data[0]);
            start = 1;
        }
        for (let index = start; index < data.length; index++) {
            acc = fn(acc, recordByLocalId.get(data[index]), index, this);
        }
        return acc;
    }
    /**
     * @param {number} [start]
     * @param {number} [end]
     * @returns {R[]}
     */
    slice(start, end) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        return recordListFullProxy.data
            .slice(start, end)
            .map((localId) => recordByLocalId.get(localId));
    }
    /** @param {R} recordProxy */
    includes(recordProxy) {
        const recordList = toRaw(this)._raw;
        const recordListFullProxy = recordList._.downgradeProxy(recordList, this);
        return recordListFullProxy.data.includes(toRaw(recordProxy)?._raw.localId);
    }
    reverse() {
        const recordList = toRaw(this)._raw;
        throw new Error(
            `Cannot reverse() record list "${recordList._.owner.Model.getName()}/${
                recordList._.name
            }": in-place mutators are not supported; use sort(), splice() or assignment instead.`,
        );
    }
    fill() {
        const recordList = toRaw(this)._raw;
        throw new Error(
            `Cannot fill() record list "${recordList._.owner.Model.getName()}/${
                recordList._.name
            }": in-place mutators are not supported; use sort(), splice() or assignment instead.`,
        );
    }
    copyWithin() {
        const recordList = toRaw(this)._raw;
        throw new Error(
            `Cannot copyWithin() record list "${recordList._.owner.Model.getName()}/${
                recordList._.name
            }": in-place mutators are not supported; use sort(), splice() or assignment instead.`,
        );
    }
}
