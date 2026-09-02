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
    record.snapshotEditState();
    for (const fieldName of Object.keys(record.changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record.changes[fieldName]._addSavePoint();
        }
    }
}

/**
 * @param {ConstructedRecord} record
 * @returns {boolean}
 */
export function restoreFromSavePoint(record) {
    return record.restoreEditState();
}

/**
 * @param {ConstructedRecord} record
 */
export function discard(record) {
    for (const fieldName of Object.keys(record.changes)) {
        if (isX2Many(record.fields[fieldName])) {
            record.changes[fieldName].discardLocked();
        }
    }
    if (restoreFromSavePoint(record)) {
        record.rebuildData();
    } else {
        record.discardChanges();
        record.clearValidity();
    }
    if (!record.isNew) {
        record.checkValidityLocked();
    }
    record.closeInvalidFieldsNotification();
    record.restoreActiveFields();
}
