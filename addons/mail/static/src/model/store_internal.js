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
    /** @type {Map<Function, true>} */
    RO_QUEUE = new Map();
    /** @type {Map<Record, true>} */
    RD_QUEUE = new Map();
    /** @type {Map<Record, true>} */
    RHD_QUEUE = new Map();
    /** @type {Error[]} */
    ERRORS = [];
    UPDATE = 0;

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
            case "compute": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                let recMap = this.FC_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FC_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "sort": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                let recMap = this.FS_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FS_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "onAdd": {
                const [record, fieldName, addedRec] =
                    /** @type {[import("./record").Record, string, import("./record").Record]} */ (
                        params
                    );
                const Model = record.Model;
                if (Model._.fieldsSort.get(fieldName)) {
                    this.ADD_QUEUE("sort", record, fieldName);
                }
                if (!Model._.fieldsOnAdd.get(fieldName)) {
                    return;
                }
                let recMap = this.FA_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FA_QUEUE.set(record, recMap);
                }
                let fieldMap = recMap.get(fieldName);
                if (!fieldMap) {
                    fieldMap = new Map();
                    recMap.set(fieldName, fieldMap);
                }
                fieldMap.set(addedRec, true);
                break;
            }
            case "onDelete": {
                const [record, fieldName, removedRec] =
                    /** @type {[import("./record").Record, string, import("./record").Record]} */ (
                        params
                    );
                const Model = record.Model;
                if (!Model._.fieldsOnDelete.get(fieldName)) {
                    return;
                }
                let recMap = this.FD_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FD_QUEUE.set(record, recMap);
                }
                let fieldMap = recMap.get(fieldName);
                if (!fieldMap) {
                    fieldMap = new Map();
                    recMap.set(fieldName, fieldMap);
                }
                fieldMap.set(removedRec, true);
                break;
            }
            case "onUpdate": {
                const [record, fieldName] =
                    /** @type {[import("./record").Record, string]} */ (params);
                let recMap = this.FU_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FU_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "hard_delete": {
                const [record] = /** @type {[import("./record").Record]} */ (params);
                if (!this.RHD_QUEUE.has(record)) {
                    this.RHD_QUEUE.set(record, true);
                }
                break;
            }
        }
    }
    /**
     * @param {RecordList} recordListFullProxy
     * @param {(r1: Record, r2: Record) => number} func
     */
    sortRecordList(recordListFullProxy, func) {
        const recordList = toRaw(recordListFullProxy)._raw;
        const recordByLocalId = recordListFullProxy._store.recordByLocalId;
        const recordsFullProxy = recordListFullProxy.data.map((localId) =>
            recordByLocalId.get(localId),
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
     * @param {string} fieldName
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
    ensureIdFieldUnchanged(record, fieldName, value) {
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
        const targetLocalId = isRecord(target)
            ? toRaw(target)._raw.localId
            : /** @type {StoreModels} */ (/** @type {unknown} */ (Model._rawStore))[
                  Model._.fieldsTargetModel.get(fieldName)
              ].localId(target);
        if (targetLocalId !== currentLocalId) {
            throw new Error(
                `Cannot change id field "${Model.getName()}/${fieldName}" of inserted record from "${currentLocalId}" to "${targetLocalId}": id fields are immutable. Delete the record and insert a new one instead.`,
            );
        }
    }
    /**
     * @param {Record} record
     * @param {Object} vals
     */
    updateFields(record, vals) {
        const fieldEntries = Object.entries(vals).concat(
            Object.getOwnPropertySymbols(vals).map(
                (sym) => /** @type {[string|symbol, any]} */ ([sym, vals[sym]]),
            ),
        );
        for (const [fieldName, value] of fieldEntries) {
            if (
                typeof fieldName === "string" &&
                record.Model._.idFields.has(fieldName)
            ) {
                this.ensureIdFieldUnchanged(record, fieldName, value);
            }
            if (isRelation(record.Model, fieldName)) {
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
     * @param {any} value
     */
    updateRelationMany(recordList, value) {
        if (isCommand(value)) {
            for (const [cmd, cmdData] of value) {
                if (Array.isArray(cmdData)) {
                    if (cmd === "ADD") {
                        recordList.add(...cmdData);
                    } else if (cmd === "ADD.noinv") {
                        recordList._.addNoinv(recordList, ...cmdData);
                    } else if (cmd === "DELETE.noinv") {
                        recordList._.deleteNoinv(recordList, ...cmdData);
                    } else {
                        recordList.delete(...cmdData);
                    }
                } else {
                    if (cmd === "ADD") {
                        recordList.add(cmdData);
                    } else if (cmd === "ADD.noinv") {
                        recordList._.addNoinv(recordList, cmdData);
                    } else if (cmd === "DELETE.noinv") {
                        recordList._.deleteNoinv(recordList, cmdData);
                    } else {
                        recordList.delete(cmdData);
                    }
                }
            }
        } else if ([null, false, undefined].includes(value)) {
            recordList.clear();
        } else if (!Array.isArray(value)) {
            recordList._.assign(recordList, [value]);
        } else {
            recordList._.assign(recordList, value);
        }
    }
    /**
     * @param {RecordList} recordList
     * @param {any} value
     */
    updateRelationOne(recordList, value) {
        if (isCommand(value)) {
            const [cmd, cmdData] = value.at(-1);
            if (cmd === "ADD") {
                recordList.add(cmdData);
            } else if (cmd === "ADD.noinv") {
                recordList._.addNoinv(recordList, cmdData);
            } else if (cmd === "DELETE.noinv") {
                recordList._.deleteNoinv(recordList, cmdData);
            } else {
                recordList.delete(cmdData);
            }
        } else if ([null, false, undefined].includes(value)) {
            recordList.clear();
        } else {
            recordList.add(value);
        }
    }
}
