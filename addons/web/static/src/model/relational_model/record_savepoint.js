// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_savepoint */

import { isX2Many } from "./field_context.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */
/** @import { RecordEditState } from "@web/model/relational_model/record_edit_state" */

/**
 * `_editState` is set in `setup()`, which `DataPoint`'s constructor calls, so
 * every constructed record has one. It cannot be declared as a class field to
 * say so: field initializers run *after* the base constructor, and `setup()`
 * reaches `_setData()`, which reads the edit state — a field would blank it
 * first.
 *
 * @typedef {RelationalRecord & { _editState: RecordEditState }} ConstructedRecord
 */

export { createSavePoint } from "./record_edit_state.js";

/**
 * Snapshot the record's pending edits, and every x2many list it has staged
 * commands on. The state itself belongs to `RecordEditState`; what lives here
 * is the recursion into the children, which the edit state cannot see.
 *
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
 * @returns {boolean} whether a savepoint was actually restored
 */
export function restoreFromSavePoint(record) {
    return record._editState.restoreSnapshot();
}

/**
 * Drop the pending edits: back to the parked snapshot if a sub-flow left one,
 * otherwise back to the server values.
 *
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
        // Only on this branch: the snapshot restore has already put the
        // validity flags back, and clearing them would discard exactly what
        // it restored.
        record._clearValidity();
    }
    if (!record.isNew) {
        record._checkValidity();
    }
    record._closeInvalidFieldsNotification();
    record._closeInvalidFieldsNotification = () => {};
    record._restoreActiveFields();
}
