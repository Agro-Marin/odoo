/** @odoo-module native */
/** @typedef {import("./record").Record} Record */
/** @typedef {import("./record_list").RecordList} RecordList */

import { htmlEscape, markup, toRaw } from "@odoo/owl";
import { deserializeDate, deserializeDateTime } from "@web/core/l10n/dates";
import { luxon } from "@web/core/l10n/luxon";

import { isCommand, isMany, isRecord, isRelation } from "./misc.js";
import { RecordInternal } from "./record_internal.js";
const Markup = markup().constructor;

export class StoreInternal extends RecordInternal {
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FC_QUEUE = new Map(); // field-computes
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FS_QUEUE = new Map(); // field-sorts
    /** @type {Map<import("./record").Record, Map<string, Map<import("./record").Record, true>>>} */
    FA_QUEUE = new Map(); // field-onadds
    /** @type {Map<import("./record").Record, Map<string, Map<import("./record").Record, true>>>} */
    FD_QUEUE = new Map(); // field-ondeletes
    /** @type {Map<import("./record").Record, Map<string, true>>} */
    FU_QUEUE = new Map(); // field-onupdates
    /** @type {Map<Function, true>} */
    RO_QUEUE = new Map(); // record-onchanges
    /** @type {Map<Record, true>} */
    RD_QUEUE = new Map(); // record-deletes
    /** @type {Map<Record, true>} */
    RHD_QUEUE = new Map(); // record-hard-deletes
    ERRORS = [];
    UPDATE = 0;

    /**
     * @param {"compute"|"sort"|"onAdd"|"onDelete"|"onUpdate"|"hard_delete"} type
     * @param {...any} params
     */
    ADD_QUEUE(type, ...params) {
        switch (type) {
            case "delete": {
                /** @type {import("./record").Record} */
                const [record] = params;
                if (!this.RD_QUEUE.has(record)) {
                    this.RD_QUEUE.set(record, true);
                }
                break;
            }
            case "compute": {
                /** @type {[import("./record").Record, string]} */
                const [record, fieldName] = params;
                let recMap = this.FC_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FC_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "sort": {
                /** @type {[import("./record").Record, string]} */
                const [record, fieldName] = params;
                let recMap = this.FS_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FS_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "onAdd": {
                /** @type {[import("./record").Record, string, import("./record").Record]} */
                const [record, fieldName, addedRec] = params;
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
                /** @type {[import("./record").Record, string, import("./record").Record]} */
                const [record, fieldName, removedRec] = params;
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
                /** @type {[import("./record").Record, string]} */
                const [record, fieldName] = params;
                let recMap = this.FU_QUEUE.get(record);
                if (!recMap) {
                    recMap = new Map();
                    this.FU_QUEUE.set(record, recMap);
                }
                recMap.set(fieldName, true);
                break;
            }
            case "hard_delete": {
                // pure enqueue: the soft-delete mutations (deletion flags,
                // registry unregistration) happen in the RD flush step.
                /** @type {import("./record").Record} */
                const [record] = params;
                if (!this.RHD_QUEUE.has(record)) {
                    this.RHD_QUEUE.set(record, true);
                }
                break;
            }
        }
    }
    /** @param {RecordList<Record>} recordListFullProxy */
    sortRecordList(recordListFullProxy, func) {
        const recordList = toRaw(recordListFullProxy)._raw;
        // sort on copy of list so that reactive observers not triggered while sorting
        const recordsFullProxy = recordListFullProxy.data.map((localId) =>
            recordListFullProxy._store.recordByLocalId.get(localId),
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
        const fieldType = Model._.fieldsType.get(fieldName);
        const fieldHtml = Model._.fieldsHtml.get(fieldName);
        // ensure each field write goes through the proxy exactly once to trigger reactives
        const targetRecord = record._.proxyUsed.has(fieldName) ? record : record._proxy;
        let shouldChange = record[fieldName] !== value;
        if (fieldType === "datetime" && value) {
            if (!(value instanceof luxon.DateTime)) {
                value = deserializeDateTime(value);
            }
            shouldChange = !record[fieldName] || !value.equals(record[fieldName]);
        }
        if (fieldType === "date" && value) {
            if (!(value instanceof luxon.DateTime)) {
                value = deserializeDate(value);
            }
            shouldChange = !record[fieldName] || !value.equals(record[fieldName]);
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
                record[fieldName]?.toString() !== newValue?.toString() ||
                record[fieldName] instanceof Markup !== newValue instanceof Markup;
        }
        if (shouldChange) {
            record._.updatingAttrs.set(fieldName, true);
            try {
                targetRecord[fieldName] = newValue;
            } finally {
                // a leaked flag would make the next write to this field
                // bypass updateFields entirely (see the proxy set trap)
                record._.updatingAttrs.delete(fieldName);
            }
        }
    }
    /**
     * Id fields are the record's identity: `localId`, `Model.records` and
     * `store.recordByLocalId` are all keyed on them. Rewriting one on an
     * inserted record would desync those registries (duplicate on next
     * insert, `get()` misses), so throw instead of corrupting.
     *
     * @param {Record} record
     * @param {string} fieldName
     * @param {any} value
     */
    ensureIdFieldUnchanged(record, fieldName, value) {
        const Model = record.Model;
        if (!isRelation(Model, fieldName)) {
            const fieldType = Model._.fieldsType.get(fieldName);
            if (fieldType === "date" || fieldType === "datetime") {
                return; // stored values are normalized: strict compare would false-positive
            }
            const current = record[fieldName];
            if (
                current === undefined ||
                current === null ||
                current === false ||
                current === "" ||
                value === undefined
            ) {
                // unset class default: this is the initial fill of a freshly
                // created record (localId was derived from the insert data
                // before fields were populated), not a change
                return;
            }
            let incoming = value;
            if (Model._.fieldsHtml.get(fieldName)) {
                // normalize like updateAttr does, so the serialized
                // ["markup", html] insert form compares against the stored
                // Markup value
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
                // String(): Markup and other wrapper values are identity-
                // distinct but localId-equal when their string form matches
                return;
            }
            throw new Error(
                `Cannot change id field "${Model.getName()}/${fieldName}" of inserted record from "${current}" to "${value}" (localId: ${
                    record.localId
                }): id fields are immutable. Delete the record and insert a new one instead.`,
            );
        }
        // fields.One participating in the id
        const currentLocalId = record[fieldName].data[0];
        if (!currentLocalId) {
            return;
        }
        let target = value;
        if (isCommand(value)) {
            const [cmd, cmdData] = value.at(-1);
            if (cmd === "DELETE" || cmd === "DELETE.noinv") {
                return; // clearing is done by deletion flows
            }
            target = cmdData;
        }
        if (target === null || target === false || target === undefined) {
            return;
        }
        const targetLocalId = isRecord(target)
            ? toRaw(target)._raw.localId
            : Model._rawStore[Model._.fieldsTargetModel.get(fieldName)].localId(target);
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
            Object.getOwnPropertySymbols(vals).map((sym) => [sym, vals[sym]]),
        );
        for (const [fieldName, value] of fieldEntries) {
            if (
                typeof fieldName === "string" &&
                record.Model._.idFields.has(fieldName)
            ) {
                this.ensureIdFieldUnchanged(record, fieldName, value);
            }
            if (
                !record.Model._.fields.get(fieldName) ||
                record.Model._.fieldsAttr.get(fieldName)
            ) {
                this.updateAttr(record, fieldName, value);
            } else {
                this.updateRelation(record, fieldName, value);
            }
        }
    }
    /**
     * @param {Record} record
     * @param {string} fieldName
     * @param {any} value
     */
    updateRelation(record, fieldName, value) {
        /** @type {RecordList<Record>} */
        const recordList = record[fieldName];
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
                    // single call: add() dedupes bulk data with a Set
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
     * @returns {boolean} whether the value has changed
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
