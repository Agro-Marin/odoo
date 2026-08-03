// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_savepoint */

import { isX2Many } from "./field_context.js";

/** @import { RecordContract } from "@web/model/relational_model/record_contract" */

/**
 * Declared against the record CONTRACT rather than `RelationalRecord`, so
 * reaching past it is a typecheck failure instead of a silent entry in the
 * private-access budget. See `record_contract.js`.
 *
 * This replaces a local `RelationalRecord & { _editState }` intersection, which
 * existed because `_editState` is set in `setup()` — called by `DataPoint`'s
 * constructor — and so cannot be declared as a class field: field initializers
 * run *after* the base constructor, and `setup()` reaches `_setData()`, which
 * reads the edit state, so a field would blank it first. The contract names
 * `_editState` outright, which says the same thing without the intersection.
 *
 * @typedef {RecordContract} ConstructedRecord
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
    record.closeInvalidFieldsNotification();
    record._restoreActiveFields();
}
