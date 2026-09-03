/** @odoo-module native */
import { markRaw, reactive, toRaw } from "@odoo/owl";

import { isOne as isOneField, isRecord } from "./misc.js";

/**
 * @typedef {import("./record").Record} Record
 */
/** @typedef {import("./record").StoreModels} StoreModels */

/**
 * @param {Record} record
 * @param {string} fieldName
 * @returns {RecordList}
 */
function relationOf(record, fieldName) {
    return /** @type {Object<string, RecordList>} */ (/** @type {unknown} */ (record))[
        fieldName
    ];
}

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
    return isOneField(reclist._.owner.Model, reclist._.name);
}

/**
 * @template {Record} R
 * @param {RecordList<R>} recordList
 * @param {RecordList<R>} recordListFullProxy
 * @returns {Map<string, R>}
 */
function recordByLocalIdFor(recordList, recordListFullProxy) {
    const recordByLocalId = /** @type {Map<string, R>} */ (
        /** @type {unknown} */ (recordListFullProxy._store.recordByLocalId)
    );
    const subscribes =
        recordListFullProxy !== recordList._proxyInternal &&
        recordListFullProxy !== recordList;
    return subscribes ? recordByLocalId : toRaw(recordByLocalId);
}

/**
 * @template {Record} R
 * @param {RecordList<R>} receiver
 * @returns {{list: RecordList<R>, proxy: RecordList<R>, byLocalId: Map<string, R>, data: string[]}}
 */
function cursorOf(receiver) {
    const list = toRaw(receiver)._raw;
    const proxy = list._.downgradeProxy(list, receiver);
    return {
        list,
        proxy,
        byLocalId: recordByLocalIdFor(list, proxy),
        data: proxy.data,
    };
}

/**
 * @param {RecordList<any>} recordList
 * @param {string|symbol} name
 * @param {RecordList<any>} receiver
 */
function recordListGet(recordList, name, receiver) {
    const recordListFullProxy = recordList._.downgradeProxy(recordList, receiver);
    if (
        typeof name === "symbol" ||
        (name !== "length" && Object.prototype.hasOwnProperty.call(recordList, name)) ||
        Object.prototype.hasOwnProperty.call(recordList.constructor.prototype, name)
    ) {
        let res = Reflect.get(recordList, name, receiver);
        if (typeof res === "function") {
            res = res.bind(recordListFullProxy);
        }
        return res;
    }
    if (name === "length") {
        return recordListFullProxy.data.length;
    }
    if (!window.isNaN(parseInt(name))) {
        const index = parseInt(name);
        return recordListFullProxy._store.recordByLocalId.get(
            recordListFullProxy.data[index],
        );
    }
    if (Object.prototype.hasOwnProperty.call(Array.prototype, name)) {
        throw new Error(
            `Array.prototype.${name}() is not supported on record list "${recordList._.owner.Model.getName()}/${
                recordList._.name
            }": reimplement it over "data" in RecordList before using it.`,
        );
    }
    return Reflect.get(recordList, name, receiver);
}
/**
 * @param {RecordList<any>} recordList
 * @param {RecordList<any>} recordListProxy
 * @param {string} name
 * @param {any} val
 */
function recordListSetIndex(recordList, recordListProxy, name, val) {
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
        /** @param {Record} newRecord */
        function recordListSet_Insert(newRecord) {
            const oldLocalId = recordList.data[index];
            if (oldLocalId === newRecord.localId) {
                return;
            }
            if (oldLocalId === undefined) {
                recordList._.attach(recordList, newRecord, index);
            } else {
                recordList._.withdraw(recordList, oldLocalId);
                recordList._.replace(recordList, index, newRecord);
            }
        },
    );
}
/**
 * @param {RecordList<any>} recordList
 * @param {RecordList<any>} recordListProxy
 * @param {any} val
 */
function recordListSetLength(recordList, recordListProxy, val) {
    const newLength = parseInt(val);
    if (newLength > recordList.data.length) {
        throw new Error(
            `Cannot grow record list "${recordList._.owner.Model.getName()}/${
                recordList._.name
            }" from ${
                recordList.data.length
            } to ${newLength} by assigning length: use add()/push() to insert records`,
        );
    }
    if (newLength < recordList.data.length) {
        recordList.splice.call(
            recordListProxy,
            newLength,
            recordList.data.length - newLength,
        );
    }
}
/**
 * @param {RecordList<any>} recordList
 * @param {string|symbol} name
 * @param {any} val
 * @param {RecordList<any>} recordListProxy
 * @returns {boolean}
 */
function recordListSet(recordList, name, val, recordListProxy) {
    const store = recordList._store;
    return store.MAKE_UPDATE(function recordListSet() {
        if (typeof name !== "symbol" && !window.isNaN(parseInt(name))) {
            recordListSetIndex(recordList, recordListProxy, name, val);
        } else if (name === "length") {
            recordListSetLength(recordList, recordListProxy, val);
        } else {
            return Reflect.set(recordList, name, val, recordListProxy);
        }
        return true;
    });
}
/**
 * @param {RecordList<any>} recordList
 * @returns {RecordList<any>}
 */
function makeRecordListProxy(recordList) {
    return new Proxy(recordList, {
        get: (recordList, name, receiver) => recordListGet(recordList, name, receiver),
        set: (recordList, name, val, recordListProxy) =>
            recordListSet(recordList, name, val, recordListProxy),
    });
}
/**
 * @template {Record} R
 * @param {RecordList<R>} receiver
 * @returns {{list: RecordList<R>, proxy: RecordList<R>, store: import("models").Store}}
 */
function mutatorOf(receiver) {
    const list = toRaw(receiver)._raw;
    return {
        list,
        proxy: list._.downgradeProxy(list, receiver),
        store: list._store,
    };
}

/**
 * Membership engine of a record list. `insert` is the only place that writes
 * the inverse side (`withdraw` is its DELETE spelling); `attach`, `detach`,
 * `replace` and `release` touch this list's data and bookkeeping alone.
 */
class RecordListInternal {
    /** @type {string} */
    name;
    /** @type {Record} */
    owner;

    /**
     * @param {RecordList} recordList
     * @param {Record} record
     * @param {number} [index] appended when omitted
     */
    attach(recordList, record, index) {
        const data = recordList._proxy.data;
        if (index === undefined || index >= data.length) {
            data.push(record.localId);
        } else {
            recordList._proxy.data = data.toSpliced(index, 0, record.localId);
        }
        this.syncLength(recordList);
        record._.uses.add(recordList);
        recordList._store._.ADD_QUEUE("onAdd", this.owner, this.name, record);
    }
    /**
     * @param {RecordList} recordList
     * @param {number} index
     * @returns {Record|undefined}
     */
    detach(recordList, index) {
        const data = recordList._proxy.data;
        const localId = data[index];
        if (isOne(recordList)) {
            data.pop();
        } else {
            recordList._proxy.data = data.toSpliced(index, 1);
        }
        this.syncLength(recordList);
        return this.release(recordList, localId);
    }
    /**
     * @param {RecordList} recordList
     * @param {number} index
     * @param {Record} record
     * @returns {Record|undefined} the record previously at that index
     */
    replace(recordList, index, record) {
        const old = this.release(recordList, recordList.data[index]);
        recordList._proxy.data[index] = record.localId;
        record._.uses.add(recordList);
        recordList._store._.ADD_QUEUE("onAdd", this.owner, this.name, record);
        return old;
    }
    /**
     * Bookkeeping of a record that has left (or is leaving) this list's data.
     * @param {RecordList} recordList
     * @param {string} localId
     * @returns {Record|undefined}
     */
    release(recordList, localId) {
        const recordProxy = toRaw(recordList._store.recordByLocalId).get(localId);
        if (!recordProxy) {
            return undefined;
        }
        const record = toRaw(recordProxy)._raw;
        record._.uses.delete(recordList);
        recordList._store._.ADD_QUEUE("onDelete", this.owner, this.name, record);
        return record;
    }
    /**
     * Withdraws the owner from the inverse of the record with that localId.
     * @param {RecordList} recordList
     * @param {string} localId
     */
    withdraw(recordList, localId) {
        const recordProxy = toRaw(recordList._store.recordByLocalId).get(localId);
        if (recordProxy) {
            this.insert(recordList, recordProxy, undefined, { mode: "DELETE" });
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {...Record} records
     */
    addNoinv(recordList, ...records) {
        const self = this;
        if (isOne(recordList)) {
            const last = records.at(-1);
            if (isRecord(last) && last.in(recordList)) {
                return;
            }
            self.insert(
                recordList,
                last,
                /** @param {Record} record */
                function recordList_AddNoInvOneInsert(record) {
                    if (record.localId === recordList.data[0]) {
                        return;
                    }
                    const old = recordList.data.length
                        ? self.replace(recordList, 0, record)
                        : self.attach(recordList, record, 0);
                    const inverse = getInverse(recordList);
                    if (old && inverse && !old.Model._.fieldsCompute.get(inverse)) {
                        const oldInverse = toRaw(relationOf(old, inverse))._raw;
                        oldInverse._.deleteNoinv(oldInverse, self.owner);
                    }
                },
                { inv: false },
            );
            return;
        }
        for (const val of records) {
            if (isRecord(val) && val.in(recordList)) {
                continue;
            }
            self.insert(
                recordList,
                val,
                /** @param {Record} record */
                function recordList_AddNoInvManyInsert(record) {
                    if (recordList.data.indexOf(record.localId) === -1) {
                        self.attach(recordList, record);
                    }
                },
                { inv: false },
            );
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {Record[]|any[]} data
     */
    assign(recordList, data) {
        const self = this;
        const store = recordList._store;
        return store.MAKE_UPDATE(function recordListAssign() {
            /** @type {Record[]|Set<Record>|RecordList} */
            const collection = isRecord(data)
                ? [/** @type {Record} */ (/** @type {unknown} */ (data))]
                : data;
            const vals = [...collection].filter(
                (val) => val !== undefined && val !== null && val !== false,
            );
            const oldLocalIds = recordList.data.slice();
            const oldLocalIdSet = new Set(oldLocalIds);
            const newLocalIdSet = new Set();
            /** @type {string[]} */
            const newLocalIds = [];
            for (const val of vals) {
                const record = self.insert(
                    recordList,
                    val,
                    /** @param {Record} record */
                    function recordListAssignInsert(record) {
                        if (
                            !oldLocalIdSet.has(record.localId) &&
                            !newLocalIdSet.has(record.localId)
                        ) {
                            record._.uses.add(recordList);
                            store._.ADD_QUEUE("onAdd", self.owner, self.name, record);
                        }
                    },
                    {
                        inv: !(
                            isRecord(val) && oldLocalIdSet.has(toRaw(val)._raw.localId)
                        ),
                    },
                );
                if (!record || newLocalIdSet.has(record.localId)) {
                    continue;
                }
                newLocalIdSet.add(record.localId);
                newLocalIds.push(record.localId);
            }
            for (const localId of oldLocalIds) {
                if (newLocalIdSet.has(localId)) {
                    continue;
                }
                const oldRecordProxy = toRaw(store.recordByLocalId).get(localId);
                if (!oldRecordProxy) {
                    continue;
                }
                self.insert(
                    recordList,
                    oldRecordProxy,
                    /** @param {Record} oldRecord */
                    function recordListAssignDelete(oldRecord) {
                        oldRecord._.uses.delete(recordList);
                        store._.ADD_QUEUE("onDelete", self.owner, self.name, oldRecord);
                    },
                    { mode: "DELETE" },
                );
            }
            const hasChanged =
                newLocalIds.length !== recordList.data.length ||
                recordList.data.some((localId, i) => localId !== newLocalIds[i]);
            if (hasChanged) {
                recordList._proxy.data = newLocalIds;
                self.syncLength(recordList);
            }
        });
    }
    /**
     * @param {RecordList} recordList
     * @param {...Record} records
     */
    deleteNoinv(recordList, ...records) {
        const self = this;
        for (const val of records) {
            self.insert(
                recordList,
                val,
                /** @param {Record} record */
                function recordList_DeleteNoInv_Insert(record) {
                    const index = recordList.data.indexOf(record.localId);
                    if (index !== -1) {
                        self.detach(recordList, index);
                    }
                },
                { inv: false },
            );
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {RecordList} fullProxy
     */
    downgradeProxy(recordList, fullProxy) {
        return recordList._proxy === fullProxy ? recordList._proxyInternal : fullProxy;
    }
    /**
     * @param {RecordList} recordList
     * @param {Record|any} val
     * @param {(record: Record) => void} [fn]
     * @param {Object} [options={}]
     * @param {boolean} [options.inv=true]
     * @param {"ADD"|"DELETE"} [options.mode="ADD"]
     */
    insert(recordList, val, fn, { inv = true, mode = "ADD" } = {}) {
        if (val === undefined || val === null || val === false) {
            return undefined;
        }
        const inverse = getInverse(recordList);
        const targetModel = getTargetModel(recordList);
        if (typeof val !== "object") {
            if (
                Array.isArray(
                    /** @type {StoreModels} */ (
                        /** @type {unknown} */ (recordList._store)
                    )[targetModel].id,
                )
            ) {
                throw new Error(
                    `Cannot insert "${val}" on relational field "${recordList._.owner.Model.getName()}/${
                        recordList._.name
                    }": target model "${targetModel}" doesn't support single-id data!`,
                );
            }
            val = {
                [/** @type {StoreModels} */ (
                    /** @type {unknown} */ (recordList._store)
                )[targetModel].id]: val,
            };
        }
        if (inverse && inv) {
            const command = [
                [mode === "ADD" ? "ADD.noinv" : "DELETE.noinv", recordList._.owner],
            ];
            if (isRecord(val)) {
                const target = val._raw === val ? val._proxy : val;
                target[inverse] = command;
            } else {
                val = { ...val, [inverse]: command };
            }
        }
        /** @type {Record} */
        let newRecordProxy;
        if (!isRecord(val)) {
            newRecordProxy = /** @type {StoreModels} */ (
                /** @type {unknown} */ (recordList._store)
            )[targetModel].preinsert(val);
        } else {
            newRecordProxy = val;
        }
        const newRecord = toRaw(newRecordProxy)._raw;
        fn?.(newRecord);
        if (!isRecord(val)) {
            /** @type {StoreModels} */ (/** @type {unknown} */ (recordList._store))[
                targetModel
            ].insert(val);
        }
        return newRecord;
    }
    /** @param {RecordList} reclist */
    syncLength(reclist) {
        reclist.length = reclist.data.length;
    }
}

/**
 * @template {Record} [R=Record]
 * @extends {Array<R>}
 */
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
        const recordListProxyInternal = makeRecordListProxy(recordList);
        recordList._proxyInternal = recordListProxyInternal;
        recordList._proxy = reactive(recordListProxyInternal);
        return recordList;
    }
    /** @param {R[]} records */
    push(...records) {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListPush() {
            for (const val of records) {
                recordList._.insert(
                    recordList,
                    val,
                    /** @param {Record} record */
                    (record) => recordList._.attach(recordList, record),
                );
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @returns {R} */
    pop() {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListPop() {
            return recordList.splice.call(
                recordListFullProxy,
                recordListFullProxy.data.length - 1,
                1,
            )[0];
        });
    }
    /** @returns {R} */
    shift() {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListShift() {
            return recordList.splice.call(recordListFullProxy, 0, 1)[0];
        });
    }
    /** @param {R[]} records */
    unshift(...records) {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListUnshift() {
            for (let i = records.length - 1; i >= 0; i--) {
                recordList._.insert(
                    recordList,
                    records[i],
                    /** @param {Record} record */
                    (record) => recordList._.attach(recordList, record, 0),
                );
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @param {R} recordProxy */
    indexOf(recordProxy) {
        return cursorOf(this).data.indexOf(toRaw(recordProxy)?._raw.localId);
    }
    /** @param {R} recordProxy */
    lastIndexOf(recordProxy) {
        return cursorOf(this).data.lastIndexOf(toRaw(recordProxy)?._raw.localId);
    }
    /**
     * @param {number} [start]
     * @param {number} [deleteCount]
     * @param {...R} [newRecordsProxy]
     * @returns {R[]} the removed records
     */
    splice(start, deleteCount, ...newRecordsProxy) {
        const { list: recordList, store } = mutatorOf(this);
        const length = recordList.data.length;
        const relativeStart = Math.trunc(start) || 0;
        const actualStart =
            relativeStart < 0
                ? Math.max(length + relativeStart, 0)
                : Math.min(relativeStart, length);
        const actualDeleteCount =
            start === undefined
                ? 0
                : deleteCount === undefined
                  ? length - actualStart
                  : Math.min(
                        Math.max(Math.trunc(deleteCount) || 0, 0),
                        length - actualStart,
                    );
        return store.MAKE_UPDATE(function recordListSplice() {
            const removed = [];
            for (const localId of recordList.data.slice(
                actualStart,
                actualStart + actualDeleteCount,
            )) {
                recordList._.withdraw(recordList, localId);
                const record = recordList._.release(recordList, localId);
                if (record) {
                    removed.push(record._proxy);
                }
            }
            /** @type {string[]} */
            const newLocalIds = [];
            for (const newRecordProxy of newRecordsProxy) {
                recordList._.insert(
                    recordList,
                    newRecordProxy,
                    /** @param {Record} record */
                    function recordListSpliceInsert(record) {
                        record._.uses.add(recordList);
                        store._.ADD_QUEUE(
                            "onAdd",
                            recordList._.owner,
                            recordList._.name,
                            record,
                        );
                        newLocalIds.push(record.localId);
                    },
                );
            }
            const list = recordList.data.toSpliced(
                actualStart,
                actualDeleteCount,
                ...newLocalIds,
            );
            if (isOne(recordList) && actualStart === 0 && actualDeleteCount === 1) {
                if (list.length === 0) {
                    recordList._proxy.data.pop();
                } else {
                    recordList._proxy.data[0] = list[0];
                }
            } else {
                recordList._proxy.data = list;
            }
            recordList._.syncLength(recordList);
            return removed;
        });
    }
    /** @param {(a: R, b: R) => number} func */
    sort(func) {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListSort() {
            recordList._store._.sortRecordList(recordListFullProxy, func);
            return recordListFullProxy;
        });
    }
    /** @param {...(R[]|RecordList<R>)} collections */
    concat(...collections) {
        const { data, byLocalId } = cursorOf(this);
        return data
            .map((localId) => byLocalId.get(localId))
            .concat(...collections.map((c) => [...c]));
    }
    /**
     * @param {...R} records
     * @returns {R|R[]}
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
                    return toRaw(last)._raw._proxy;
                }
                return recordList._.insert(
                    recordList,
                    last,
                    /** @param {Record} record */
                    function recordListAddInsertOne(record) {
                        const [oldLocalId] = recordList.data;
                        if (oldLocalId === record.localId) {
                            return;
                        }
                        if (oldLocalId === undefined) {
                            recordList._.attach(recordList, record, 0);
                        } else {
                            recordList._.withdraw(recordList, oldLocalId);
                            recordList._.replace(recordList, 0, record);
                        }
                    },
                )?._proxy;
            }
            const res = [];
            const known = records.length > 1 ? new Set(recordList.data) : null;
            /** @param {string} localId */
            const has = (localId) =>
                known ? known.has(localId) : recordList.data.includes(localId);
            for (const val of records) {
                if (isRecord(val) && has(toRaw(val)._raw.localId)) {
                    res.push(toRaw(val)._raw._proxy);
                    continue;
                }
                const rec = recordList._.insert(
                    recordList,
                    val,
                    /** @param {Record} record */
                    function recordListAddInsertMany(record) {
                        if (!has(record.localId)) {
                            recordList._.attach(recordList, record);
                            known?.add(record.localId);
                        }
                    },
                );
                res.push(rec?._proxy);
            }
            return records.length === 1 ? res[0] : res;
        });
    }
    /** @param {...R} records */
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
                    target = /** @type {StoreModels} */ (
                        /** @type {unknown} */ (recordList._store)
                    )[getTargetModel(recordList)].get(val);
                    if (!target) {
                        continue;
                    }
                }
                recordList._.insert(
                    recordList,
                    target,
                    /** @param {Record} record */
                    function recordListDelete_Insert(record) {
                        const index = recordList.data.indexOf(record.localId);
                        if (index !== -1) {
                            recordList._.detach(recordList, index);
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
            recordList._proxy.data = [];
            recordList._.syncLength(recordList);
            for (let i = oldLocalIds.length - 1; i >= 0; i--) {
                recordList._.withdraw(recordList, oldLocalIds[i]);
                recordList._.release(recordList, oldLocalIds[i]);
            }
        });
    }
    /** @yields {R} */
    *[Symbol.iterator]() {
        const { data, byLocalId } = cursorOf(this);
        for (const localId of data) {
            yield byLocalId.get(localId);
        }
    }
    /** @yields {R} */
    *values() {
        yield* this;
    }
    /** @yields {number} */
    *keys() {
        const { data } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            yield index;
        }
    }
    /** @yields {[number, R]} */
    *entries() {
        const { data, byLocalId } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            yield [index, byLocalId.get(data[index])];
        }
    }
    /** @param {number} index */
    at(index) {
        const { data, byLocalId } = cursorOf(this);
        return byLocalId.get(data.at(index));
    }
    /** @param {(record: R, index: number, recordList: this) => any} fn */
    map(fn) {
        const { data, byLocalId } = cursorOf(this);
        return data.map((localId, index) => fn(byLocalId.get(localId), index, this));
    }
    /**
     * @param {(record: R, index: number, recordList: this) => any} fn
     * @returns {any[]}
     */
    flatMap(fn) {
        return this.map(fn).flat();
    }
    /**
     * @param {(record: R, index: number, recordList: this) => boolean} fn
     * @returns {R[]}
     */
    filter(fn) {
        const { data, byLocalId } = cursorOf(this);
        const result = [];
        for (let index = 0; index < data.length; index++) {
            const recordProxy = byLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                result.push(recordProxy);
            }
        }
        return result;
    }
    /**
     * @param {(record: R, index: number, recordList: this) => boolean} fn
     * @returns {R|undefined}
     */
    find(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            const recordProxy = byLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                return recordProxy;
            }
        }
        return undefined;
    }
    /**
     * @param {(record: R, index: number, recordList: this) => boolean} fn
     * @returns {R|undefined}
     */
    findLast(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = data.length - 1; index >= 0; index--) {
            const recordProxy = byLocalId.get(data[index]);
            if (fn(recordProxy, index, this)) {
                return recordProxy;
            }
        }
        return undefined;
    }
    /**
     * @param {(record: R, index: number, recordList: this) => boolean} fn
     * @returns {number}
     */
    findLastIndex(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = data.length - 1; index >= 0; index--) {
            if (fn(byLocalId.get(data[index]), index, this)) {
                return index;
            }
        }
        return -1;
    }
    /** @param {(record: R, index: number, recordList: this) => boolean} fn */
    findIndex(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            if (fn(byLocalId.get(data[index]), index, this)) {
                return index;
            }
        }
        return -1;
    }
    /** @param {(record: R, index: number, recordList: this) => boolean} fn */
    some(fn) {
        return this.findIndex(fn) !== -1;
    }
    /** @param {(record: R, index: number, recordList: this) => boolean} fn */
    every(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            if (!fn(byLocalId.get(data[index]), index, this)) {
                return false;
            }
        }
        return true;
    }
    /** @param {(record: R, index: number, recordList: this) => void} fn */
    forEach(fn) {
        const { data, byLocalId } = cursorOf(this);
        for (let index = 0; index < data.length; index++) {
            fn(byLocalId.get(data[index]), index, this);
        }
    }
    /**
     * @param {(acc: any, record: R, index: number, recordList: this) => any} fn
     * @param {...any} init
     * @returns {any}
     */
    reduce(fn, ...init) {
        const { data, byLocalId } = cursorOf(this);
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
            acc = byLocalId.get(data[0]);
            start = 1;
        }
        for (let index = start; index < data.length; index++) {
            acc = fn(acc, byLocalId.get(data[index]), index, this);
        }
        return acc;
    }
    /**
     * @param {(acc: any, record: R, index: number, recordList: this) => any} fn
     * @param {...any} init
     * @returns {any}
     */
    reduceRight(fn, ...init) {
        const { data, byLocalId } = cursorOf(this);
        let acc;
        let start = data.length - 1;
        if (init.length) {
            acc = init[0];
        } else {
            if (data.length === 0) {
                throw new TypeError(
                    "Reduce of empty record list with no initial value",
                );
            }
            acc = byLocalId.get(data[start]);
            start--;
        }
        for (let index = start; index >= 0; index--) {
            acc = fn(acc, byLocalId.get(data[index]), index, this);
        }
        return acc;
    }
    /**
     * @param {number} [start]
     * @param {number} [end]
     * @returns {R[]}
     */
    slice(start, end) {
        const { data, byLocalId } = cursorOf(this);
        return data.slice(start, end).map((localId) => byLocalId.get(localId));
    }
    /** @param {R} recordProxy */
    includes(recordProxy) {
        return cursorOf(this).data.includes(toRaw(recordProxy)?._raw.localId);
    }
    /** @param {string} [separator] */
    join(separator) {
        const { data, byLocalId } = cursorOf(this);
        return data.map((localId) => byLocalId.get(localId)).join(separator);
    }
    toString() {
        return this.join();
    }
    toLocaleString() {
        return this.join();
    }
    /**
     * @param {number} [depth]
     * @returns {any[]}
     */
    flat(depth) {
        return this.slice().flat(depth);
    }
    /** @returns {R[]} */
    toReversed() {
        return this.slice().reverse();
    }
    /**
     * @param {(a: R, b: R) => number} [func]
     * @returns {R[]}
     */
    toSorted(func) {
        return this.slice().sort(func);
    }
    /**
     * @param {number} start
     * @param {number} [deleteCount]
     * @param {...R} items
     * @returns {R[]}
     */
    toSpliced(start, deleteCount, ...items) {
        const copy = this.slice();
        if (deleteCount === undefined && items.length === 0) {
            copy.splice(start);
        } else {
            copy.splice(start, deleteCount, ...items);
        }
        return copy;
    }
    /**
     * @param {number} index
     * @param {R} value
     * @returns {R[]}
     */
    with(index, value) {
        return this.slice().with(index, value);
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
