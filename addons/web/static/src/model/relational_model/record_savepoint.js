// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_savepoint */

import { markRaw } from "@odoo/owl";

import { isX2Many } from "./field_context.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * @param {{
 *  changes?: Record<string, any>,
 *  textValues?: Record<string, any>,
 *  invalidFields?: Iterable<string>,
 *  unsetRequiredFields?: Iterable<string>,
 * }} [parts]
 * @returns {Record<string, any>}
 */
export function createSavePoint({
    changes = {},
    textValues = {},
    invalidFields = [],
    unsetRequiredFields = [],
} = {}) {
    return markRaw({
        changes: { ...changes },
        textValues: { ...textValues },
        invalidFields: [...invalidFields],
        unsetRequiredFields: [...unsetRequiredFields],
    });
}

/**
 * @param {RelationalRecord} record
 */
export function addSavePoint(record) {
    record._savePoint = createSavePoint({
        textValues: record._textValues,
        changes: record._changes,
        invalidFields: record._invalidFields,
        unsetRequiredFields: record._unsetRequiredFields,
    });
    for (const fieldName of Object.keys(record._changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record._changes[fieldName]._addSavePoint();
        }
    }
}

/**
 * @param {RelationalRecord} record
 */
export function restoreFromSavePoint(record) {
    const savePoint = record._savePoint;
    record._changes = markRaw({ ...savePoint.changes });
    record._textValues = markRaw({ ...savePoint.textValues });
    record._restoreValidity({
        invalidFields: savePoint.invalidFields,
        unsetRequiredFields: savePoint.unsetRequiredFields,
    });
    record.dirty =
        Object.keys(record._changes).length > 0 || record._invalidFields.size > 0;
    record._savePoint = undefined;
}

/**
 * @param {RelationalRecord} record
 */
export function discard(record) {
    for (const fieldName of Object.keys(record._changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record._changes[fieldName]._discard();
        }
    }
    const fromSavePoint = !!record._savePoint;
    if (fromSavePoint) {
        restoreFromSavePoint(record);
        record._rebuildData();
    } else {
        record._discardChanges();
    }
    if (!fromSavePoint) {
        record._clearValidity();
    }
    if (!record.isNew) {
        record._checkValidity();
    }
    record._closeInvalidFieldsNotification();
    record._closeInvalidFieldsNotification = () => {};
    record._restoreActiveFields();
}
