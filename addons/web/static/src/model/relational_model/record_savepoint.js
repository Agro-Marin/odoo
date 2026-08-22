// @ts-check
/** @odoo-module native */

import { isX2Many } from "@web/core/field_types";

/** @import { RecordContract } from "@web/model/relational_model/record_contract" */

/**
 * @typedef {RecordContract} ConstructedRecord
 */

export { createSavePoint } from "./record_edit_state.js";

/**
 * @param {ConstructedRecord} record
 */
export function addSavePoint(record) {
    record._editState.snapshot();
    for (const fieldName of Object.keys(record._changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record._changes[fieldName]._addSavePoint();
        }
    }
}

/**
 * @param {ConstructedRecord} record
 * @returns {boolean}
 */
export function restoreFromSavePoint(record) {
    return record._editState.restoreSnapshot();
}

/**
 * @param {ConstructedRecord} record
 */
export function discard(record) {
    for (const fieldName of Object.keys(record._changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record._changes[fieldName]._discard();
        }
    }
    if (restoreFromSavePoint(record)) {
        record._rebuildData();
    } else {
        record._discardChanges();
        record._clearValidity();
    }
    if (!record.isNew) {
        record._checkValidity();
    }
    record.closeInvalidFieldsNotification();
    record._restoreActiveFields();
}
