// @ts-check
/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @typedef {import("./record_list").RecordList} RecordList */
/** @typedef {import("./record").RecordFields} RecordFields */
/** @typedef {import("./record").StoreModels} StoreModels */

import { htmlEscape, markup, toRaw } from "@odoo/owl";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";

import { isCommand, isMany, isRecord, isRelation } from "./misc.js";
import { RecordInternal } from "./record_internal.js";
const Markup = markup("").constructor;

export class StoreInternal extends RecordInternal {
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FC_QUEUE = new Map();
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FS_QUEUE = new Map();
    /** @type {Map<import("./record").Record, Map<string, Map<import("./record").Record, true>>>} */
    FA_QUEUE = new Map();
    /** @type {Map<import("./record").Record, Map<string, Map<import("./record").Record, true>>>} */
    FD_QUEUE = new Map();
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FU_QUEUE = new Map();
    /** @type {Map<() => void, true>} */
    RO_QUEUE = new Map();
    /** @type {Map<Record, true>} */
    RD_QUEUE = new Map();
    /** @type {Map<Record, true>} */
    RHD_QUEUE = new Map();
    /** @type {Error[]} */
    ERRORS = [];
    UPDATE = 0;

    /**
     * @param {StoreInternal["FC_QUEUE"]} queue
     * @param {import("./record").Record} record
     * @param {string} fieldName
     */
    _queueField(queue, record, fieldName) {
        let recMap = queue.get(record);
        if (!recMap) {
            recMap = new Map();
            queue.set(record, recMap);
        }
        recMap.set(fieldName, true);
    }
    /**
     * @param {StoreInternal["FA_QUEUE"]} queue
     * @param {import("./record").Record} record
     * @param {string} fieldName
     * @param {import("./record").Record} relatedRecord
     */
    _queueRelatedRecord(queue, record, fieldName, relatedRecord) {
        let recMap = queue.get(record);
        if (!recMap) {
            recMap = new Map();
            queue.set(record, recMap);
        }
        let fieldMap = recMap.get(fieldName);
        if (!fieldMap) {
            fieldMap = new Map();
            recMap.set(fieldName, fieldMap);
        }
        fieldMap.set(relatedRecord, true);
    }
    /**
     * @overload
     * @param {"delete" | "hard_delete"} type
     * @param {Record} record
     * @returns {void}
     */
    /**
     * @overload
     * @param {"compute" | "sort" | "onUpdate"} type
     * @param {Record} record
     * @param {string} fieldName
     * @returns {void}
     */
    /**
     * @overload
     * @param {"onAdd" | "onDelete"} type
     * @param {Record} record
     * @param {string} fieldName
     * @param {Record} relatedRecord
     * @returns {void}
     */
    /**
     * @param {"delete"|"compute"|"sort"|"onAdd"|"onDelete"|"onUpdate"|"hard_delete"} type
     * @param {...any} params
     */
    ADD_QUEUE(type, ...params) {
        switch (type) {
            case "delete": {
                const [record] = /** @type {[import("./record").Record]} */ (params);
                if (!this.RD_QUEUE.has(record)) {
                    this.RD_QUEUE.set(record, true);
                }
                break;
            }
            case "hard_delete": {
                const [record] = /** @type {[import("./record").Record]} */ (params);
                if (!this.RHD_QUEUE.has(record)) {
                    this.RHD_QUEUE.set(record, true);
                }
                break;
            }
            case "compute": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                this._queueField(this.FC_QUEUE, record, fieldName);
                break;
            }
            case "sort": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                this._queueField(this.FS_QUEUE, record, fieldName);
                break;
            }
            case "onUpdate": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                this._queueField(this.FU_QUEUE, record, fieldName);
                break;
            }
            case "onAdd": {
                const [record, fieldName, addedRec] =
                    /** @type {[import("./record").Record, string, import("./record").Record]} */ (
                        params
                    );
                if (record.Model._.fieldsSort.get(fieldName)) {
                    this.ADD_QUEUE("sort", record, fieldName);
                }
                if (!record.Model._.fieldsOnAdd.get(fieldName)) {
                    return;
                }
                this._queueRelatedRecord(this.FA_QUEUE, record, fieldName, addedRec);
                break;
            }
            case "onDelete": {
                const [record, fieldName, removedRec] =
                    /** @type {[import("./record").Record, string, import("./record").Record]} */ (
                        params
                    );
                if (!record.Model._.fieldsOnDelete.get(fieldName)) {
                    return;
                }
                this._queueRelatedRecord(this.FD_QUEUE, record, fieldName, removedRec);
                break;
            }
        }
    }
    /**
     * @template {Record} R
     * @param {import("./record_list").RecordList<R>} recordListFullProxy
     * @param {(r1: R, r2: R) => number} func
     */
    sortRecordList(recordListFullProxy, func) {
        const recordList = toRaw(recordListFullProxy)._raw;
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const recordsFullProxy = recordListFullProxy.data.map(
            (localId) => /** @type {R} */ (recordByLocalId.get(localId)),
        );
        recordsFullProxy.sort(func);
        const data = recordsFullProxy.map(
            (recordFullProxy) => toRaw(recordFullProxy)._raw.localId,
        );
        const hasChanged = recordList.data.some((localId, i) => localId !== data[i]);
        if (hasChanged) {
            recordListFullProxy.data = data;
        }
    }
    /**
     * @param {Record} record
     * @param {string | symbol} fieldName
     * @param {any} value
     */
    updateAttr(record, fieldName, value) {
        const Model = record.Model;
        const fields = /** @type {RecordFields} */ (/** @type {unknown} */ (record));
        const fieldType = Model._.fieldsType.get(fieldName);
        const fieldHtml = Model._.fieldsHtml.get(fieldName);
        const targetRecord = record._.proxyUsed.has(fieldName) ? record : record._proxy;
        let shouldChange = fields[fieldName] !== value;
        if (fieldType === "datetime" && value) {
            if (!(value instanceof luxon.DateTime)) {
                value = deserializeDateTime(value);
            }
            shouldChange = !fields[fieldName] || !value.equals(fields[fieldName]);
        }
        if (fieldType === "date" && value) {
            if (!(value instanceof luxon.DateTime)) {
                value = deserializeDate(value);
            }
            shouldChange = !fields[fieldName] || !value.equals(fields[fieldName]);
        }
        let newValue = value;
        if (fieldHtml) {
            newValue =
                Array.isArray(value) && value[0] === "markup"
                    ? value[1]
                        ? markup(value[1])
                        : ""
                    : value
                      ? htmlEscape(value)
                      : "";
            shouldChange =
                fields[fieldName]?.toString() !== newValue?.toString() ||
                fields[fieldName] instanceof Markup !== newValue instanceof Markup;
        }
        if (shouldChange) {
            record._.updatingAttrs.set(fieldName, true);
            try {
                /** @type {RecordFields} */ (/** @type {unknown} */ (targetRecord))[
                    fieldName
                ] = newValue;
            } finally {
                record._.updatingAttrs.delete(fieldName);
            }
        }
    }
    /**
     * @param {Record} record
     * @param {string} fieldName
     * @param {any} value
     */
    checkIdFieldUnchanged(record, fieldName, value) {
        const Model = record.Model;
        if (!isRelation(Model, fieldName)) {
            const fieldType = Model._.fieldsType.get(fieldName);
            if (fieldType === "date" || fieldType === "datetime") {
                return;
            }
            const current = /** @type {RecordFields} */ (
                /** @type {unknown} */ (record)
            )[fieldName];
            if (
                current === undefined ||
                current === null ||
                current === false ||
                current === "" ||
                value === undefined
            ) {
                return;
            }
            let incoming = value;
            if (Model._.fieldsHtml.get(fieldName)) {
                incoming =
                    Array.isArray(value) && value[0] === "markup"
                        ? value[1]
                            ? markup(value[1])
                            : ""
                        : value
                          ? htmlEscape(value)
                          : "";
            }
            if (current === incoming || String(current) === String(incoming)) {
                return;
            }
            throw new Error(
                `Cannot change id field "${Model.getName()}/${fieldName}" of inserted record from "${current}" to "${value}" (localId: ${
                    record.localId
                }): id fields are immutable. Delete the record and insert a new one instead.`,
            );
        }
        const currentLocalId = /** @type {RecordFields} */ (
            /** @type {unknown} */ (record)
        )[fieldName].data[0];
        if (!currentLocalId) {
            return;
        }
        let target = value;
        if (isCommand(value)) {
            const [cmd, cmdData] = value.at(-1);
            if (cmd === "DELETE" || cmd === "DELETE.noinv") {
                return;
            }
            target = cmdData;
        }
        if (target === null || target === false || target === undefined) {
            return;
        }
        const targetModel = Model._.fieldsTargetModel.get(fieldName);
        if (targetModel === undefined) {
            throw new Error(
                `Missing target model for relation ${Model.getName()}.${fieldName}`,
            );
        }
        const targetLocalId = isRecord(target)
            ? toRaw(target)._raw.localId
            : /** @type {StoreModels} */ (/** @type {unknown} */ (Model._rawStore))[
                  targetModel
              ].localId(target);
        if (targetLocalId !== currentLocalId) {
            throw new Error(
                `Cannot change id field "${Model.getName()}/${fieldName}" of inserted record from "${currentLocalId}" to "${targetLocalId}": id fields are immutable. Delete the record and insert a new one instead.`,
            );
        }
    }
    /**
     * @param {Record} record
     * @param {RecordFields} vals
     */
    updateFields(record, vals) {
        const fieldEntries = /** @type {[string | symbol, any][]} */ (
            Object.entries(vals)
        ).concat(
            Object.getOwnPropertySymbols(vals).map(
                (sym) => /** @type {[string|symbol, any]} */ ([sym, vals[sym]]),
            ),
        );
        for (const [fieldName, value] of fieldEntries) {
            if (
                typeof fieldName === "string" &&
                record.Model._.idFields.has(fieldName)
            ) {
                this.checkIdFieldUnchanged(record, fieldName, value);
            }
            if (typeof fieldName === "string" && isRelation(record.Model, fieldName)) {
                this.updateRelation(record, fieldName, value);
            } else {
                this.updateAttr(record, fieldName, value);
            }
        }
    }
    /**
     * @param {Record} record
     * @param {string} fieldName
     * @param {any} value
     */
    updateRelation(record, fieldName, value) {
        /** @type {RecordList} */
        const recordList = /** @type {RecordFields} */ (
            /** @type {unknown} */ (record)
        )[fieldName];
        if (isMany(record.Model, fieldName)) {
            this.updateRelationMany(recordList, value);
        } else {
            this.updateRelationOne(recordList, value);
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {"ADD"|"DELETE"|"ADD.noinv"|"DELETE.noinv"} cmd
     * @param {any[]} args
     */
    applyRelationCommand(recordList, cmd, args) {
        switch (cmd) {
            case "ADD":
                recordList.add(...args);
                break;
            case "ADD.noinv":
                recordList._.addNoinv(recordList, ...args);
                break;
            case "DELETE.noinv":
                recordList._.deleteNoinv(recordList, ...args);
                break;
            default:
                recordList.delete(...args);
                break;
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {any} value
     */
    updateRelationMany(recordList, value) {
        if (isCommand(value)) {
            for (const [cmd, cmdData] of value) {
                this.applyRelationCommand(
                    recordList,
                    cmd,
                    Array.isArray(cmdData) ? cmdData : [cmdData],
                );
            }
        } else if ([null, false, undefined].includes(value)) {
            recordList.clear();
        } else {
            recordList._.assign(recordList, Array.isArray(value) ? value : [value]);
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {any} value
     */
    updateRelationOne(recordList, value) {
        if (isCommand(value)) {
            const [cmd, cmdData] = value.at(-1);
            this.applyRelationCommand(recordList, cmd, [cmdData]);
        } else if ([null, false, undefined].includes(value)) {
            recordList.clear();
        } else {
            recordList.add(value);
        }
    }
}
