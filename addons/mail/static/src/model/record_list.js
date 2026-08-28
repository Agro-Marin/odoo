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
    if (typeof name !== "symbol" && !window.isNaN(parseInt(name))) {
        const index = parseInt(name);
        return recordListFullProxy._store.recordByLocalId.get(
            recordListFullProxy.data[index],
        );
    }
    const array = [...recordList[Symbol.iterator].call(recordListFullProxy)];
    return /** @type {Object<string, Function>} */ (/** @type {unknown} */ (array))[
        name
    ]?.bind(array);
}
/**
 * @param {RecordList<any>} recordList
 * @param {RecordList<any>} recordListProxy
 * @param {string} name
 * @param {any} val
 */
function recordListSetIndex(recordList, recordListProxy, name, val) {
    const store = recordList._store;
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
            const oldRecordProxy =
                oldLocalId && toRaw(recordList._store.recordByLocalId).get(oldLocalId);
            const oldRecord = oldRecordProxy ? toRaw(oldRecordProxy)._raw : undefined;
            if (oldRecord?.eq(newRecord)) {
                return;
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
                    relationOf(oldRecord, inverse).delete(recordList._.owner);
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
                    relationOf(newRecord, inverse).add?.(recordList._.owner);
                }
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

export class RecordListInternal {
    /** @type {string} */
    name;
    /** @type {Record} */
    owner;

    /**
     * @param {RecordList} recordList
     * @param {...Record} records
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
                /** @param {Record} record */
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
                            const oldRecord = toRaw(old)._raw;
                            store._.ADD_QUEUE(
                                "onDelete",
                                self.owner,
                                self.name,
                                oldRecord,
                            );
                            const inverse = getInverse(recordList);
                            if (
                                inverse &&
                                !oldRecord.Model._.fieldsCompute.get(inverse)
                            ) {
                                relationOf(oldRecord, inverse).delete(self.owner);
                            }
                        }
                    }
                },
                { inv: false },
            );
            if (changed) {
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
                /** @param {Record} record */
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
            const oldRecords = recordList._proxyInternal.slice
                .call(recordList._proxy)
                .map((recordProxy) => toRaw(recordProxy)._raw);
            const oldLocalIdSet = new Set(oldRecords.map((record) => record.localId));
            const newLocalIdSet = new Set();
            const newRecords = [];
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
                        relationOf(oldRecord, inverse).delete(self.owner);
                    }
                }
            }
            const newLocalIds = newRecords.map((newRecord) => newRecord.localId);
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
     * @param {RecordList} recordList
     * @param {...Record} records
     */
    deleteNoinv(recordList, ...records) {
        const self = this;
        const store = recordList._store;
        for (const val of records) {
            let removed = false;
            const record = this.insert(
                recordList,
                val,
                /** @param {Record} record */
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
                store._.ADD_QUEUE("onDelete", self.owner, self.name, record);
            }
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
                const record = recordList._.insert(
                    recordList,
                    val,
                    /** @param {Record} record */
                    function recordListPushInsert(record) {
                        recordList._proxy.data.push(record.localId);
                        recordList._.syncLength(recordList);
                        record._.uses.add(recordList);
                    },
                );
                if (!record) {
                    continue;
                }
                store._.ADD_QUEUE(
                    "onAdd",
                    recordList._.owner,
                    recordList._.name,
                    record,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    relationOf(record, inverse).add(recordList._.owner);
                }
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @returns {R} */
    pop() {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
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
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListShift() {
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
                relationOf(record, inverse).delete(recordList._.owner);
            }
            return recordProxy;
        });
    }
    /** @param {R[]} records */
    unshift(...records) {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
        return store.MAKE_UPDATE(function recordListUnshift() {
            for (let i = records.length - 1; i >= 0; i--) {
                const record = recordList._.insert(
                    recordList,
                    records[i],
                    /** @param {Record} record */
                    (record) => {
                        recordList._proxy.data.unshift(record.localId);
                        recordList._.syncLength(recordList);
                        record._.uses.add(recordList);
                    },
                );
                if (!record) {
                    continue;
                }
                store._.ADD_QUEUE(
                    "onAdd",
                    recordList._.owner,
                    recordList._.name,
                    record,
                );
                const inverse = getInverse(recordList);
                if (inverse) {
                    relationOf(record, inverse).add(recordList._.owner);
                }
            }
            return recordListFullProxy.data.length;
        });
    }
    /** @param {R} recordProxy */
    indexOf(recordProxy) {
        return cursorOf(this).data.indexOf(toRaw(recordProxy)?._raw.localId);
    }
    /**
     * @param {number} [start]
     * @param {number} [deleteCount]
     * @param {...R} [newRecordsProxy]
     */
    splice(start, deleteCount, ...newRecordsProxy) {
        const { list: recordList, proxy: recordListFullProxy, store } = mutatorOf(this);
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
            const oldRecordLocalIds = recordList.data.slice(
                actualStart,
                actualStart + actualDeleteCount,
            );
            const oldRecords = oldRecordLocalIds
                .map((localId) => toRaw(recordList._store.recordByLocalId).get(localId))
                .filter(Boolean)
                .map((oldRecordProxy) => toRaw(oldRecordProxy)._raw);
            const list = recordListFullProxy.data.slice();
            list.splice(
                actualStart,
                actualDeleteCount,
                ...newRecordsProxy.map(
                    (newRecordProxy) => toRaw(newRecordProxy)._raw.localId,
                ),
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
                    relationOf(oldRecord, inverse).delete(recordList._.owner);
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
                    relationOf(newRecord, inverse).add(recordList._.owner);
                }
            }
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
                        if (record.localId !== recordList.data[0]) {
                            recordList.splice.call(recordList._proxy, 0, 1, record);
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
                            recordList.push.call(recordList._proxy, record);
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
                    relationOf(oldRecord, inverse).delete(recordList._.owner);
                }
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
