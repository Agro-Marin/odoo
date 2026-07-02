// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_validator - Validation orchestration: unset-required scan, invalid-field set management, and notification routing */

/**
 * Validation logic for Record field values.
 *
 * Two layers in one module:
 *
 *   1. **{@link findUnsetRequiredFields}** — pure function: determines
 *      which required fields are unset without mutating any state.
 *      Used by ``checkValidity`` below; exported so it can be
 *      unit-tested (and used directly by callers that want the scan
 *      without the side effects).
 *
 *   2. **Orchestration helpers** (``checkValidity``, ``setInvalidField``,
 *      ``resetFieldValidity``, ``removeInvalidFields``,
 *      ``displayInvalidFieldNotification``) — receive the
 *      RelationalRecord instance as first argument (delegation pattern)
 *      and mutate ``record._invalidFields`` / ``record._unsetRequiredFields``
 *      / ``record._closeInvalidFieldsNotification`` accordingly.
 *
 * The class methods on RelationalRecord remain as thin delegators so
 * sibling files (``dynamic_list.js``, ``record_save.js``, ``static_list.js``)
 * can still call ``record._checkValidity(...)`` without import churn.
 */

import { toRaw } from "@odoo/owl";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Determine which required fields in a record are unset or invalid.
 *
 * Iterates all active fields, skipping invisible and property-derived fields,
 * and checks each field type for "unset" conditions (empty string for html,
 * zero count for x2many, etc.).
 *
 * @param {Object} activeFields
 * @param {Object} fields - field definitions
 * @param {Object} data - current record data
 * @param {Object} callbacks
 * @param {(fieldName: string) => boolean} callbacks.isInvisible
 * @param {(fieldName: string) => boolean} callbacks.isRequired
 * @param {(fieldName: string, list: Object) => boolean} callbacks.isChildListValid
 *     Validates x2many child records. Called with the field name and the
 *     StaticList datapoint. Should return true if all child records are valid.
 * @returns {Set<string>} field names of unset required fields
 */
export function findUnsetRequiredFields(
    activeFields,
    fields,
    data,
    { isInvisible, isRequired, isChildListValid },
) {
    const unsetRequiredFields = new Set();
    for (const fieldName of Object.keys(activeFields)) {
        const fieldType = fields[fieldName].type;
        if (isInvisible(fieldName) || fields[fieldName].relatedPropertyField) {
            continue;
        }
        switch (fieldType) {
            case "boolean":
            case "float":
            case "integer":
            case "monetary":
                continue;
            case "html":
                if (isRequired(fieldName) && (!data[fieldName] || data[fieldName].length === 0)) {
                    unsetRequiredFields.add(fieldName);
                }
                break;
            case "one2many":
            case "many2many": {
                const list = data[fieldName];
                if (
                    (isRequired(fieldName) && !list.count) ||
                    !isChildListValid(fieldName, list)
                ) {
                    unsetRequiredFields.add(fieldName);
                }
                break;
            }
            case "properties": {
                const value = data[fieldName];
                if (value) {
                    const ok = value.every(
                        (propertyDefinition) =>
                            propertyDefinition.name &&
                            propertyDefinition.name.length &&
                            propertyDefinition.string &&
                            propertyDefinition.string.length,
                    );
                    if (!ok) {
                        unsetRequiredFields.add(fieldName);
                    }
                }
                break;
            }
            case "json": {
                const value = data[fieldName];
                const jsonEmpty =
                    value == null ||
                    (typeof value === "object" && Object.keys(value).length === 0);
                if (isRequired(fieldName) && jsonEmpty) {
                    unsetRequiredFields.add(fieldName);
                }
                break;
            }
            default:
                if (!data[fieldName] && isRequired(fieldName)) {
                    unsetRequiredFields.add(fieldName);
                }
        }
    }
    return unsetRequiredFields;
}

// ---------------------------------------------------------------------------
// Orchestration helpers (mutate ``record._invalidFields`` /
// ``record._unsetRequiredFields`` / ``record._closeInvalidFieldsNotification``)
// ---------------------------------------------------------------------------

/**
 * Run the validation algorithm on a record and update its invalid-field
 * state in place. Optionally surface a UI notification when invalid
 * fields are detected.
 *
 * Three behavioural modes (mutually exclusive, controlled by options):
 *
 *   - **silent**: scan only; return ``true`` if no unset-required field
 *     was detected, ``false`` otherwise. ``record`` state is not mutated.
 *   - **removeInvalidOnly**: prune fields from ``_unsetRequiredFields``
 *     (and the corresponding ``_invalidFields`` entries) that are no
 *     longer unset. Existing invalid-input flags (set by
 *     {@link setInvalidField}) are NOT touched — only the unset-required
 *     subset is reconciled. Used by ``_applyChanges`` to re-validate
 *     after edits without wiping user-input-validation flags.
 *   - **default**: replace the entire ``_unsetRequiredFields`` subset
 *     with the freshly scanned set. Invalid-input flags (set via
 *     {@link setInvalidField}) survive across the scan because they
 *     live in ``_invalidFields`` but are not tracked in
 *     ``_unsetRequiredFields`` — only this method's prior scan
 *     entries are cleared.
 *
 * Child x2many record validation is recursive via the child records'
 * own ``_checkValidity`` (class-method delegator), so any per-class
 * override at a deeper level remains in effect.
 *
 * @param {RelationalRecord} record
 * @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean }} [options]
 * @returns {boolean} ``true`` when the record has no invalid fields
 *  after the scan, ``false`` otherwise
 */
export function checkValidity(record, { silent, displayNotification, removeInvalidOnly } = {}) {
    const unsetRequiredFields = findUnsetRequiredFields(
        record.activeFields,
        record.fields,
        record.data,
        {
            isInvisible: (fieldName) => record._isInvisible(fieldName),
            isRequired: (fieldName) => record._isRequired(fieldName),
            isChildListValid: (_fieldName, list) =>
                list.records.every(
                    (r) =>
                        !r.dirty || r._checkValidity({ silent, removeInvalidOnly }),
                ),
        },
    );

    if (silent) {
        return !unsetRequiredFields.size;
    }

    if (removeInvalidOnly) {
        for (const fieldName of Array.from(record._unsetRequiredFields)) {
            if (!unsetRequiredFields.has(fieldName)) {
                record._unsetRequiredFields.delete(fieldName);
                record._invalidFields.delete(fieldName);
            }
        }
    } else {
        for (const fieldName of Array.from(record._unsetRequiredFields)) {
            record._invalidFields.delete(fieldName);
        }
        record._unsetRequiredFields.clear();
        for (const fieldName of unsetRequiredFields) {
            record._unsetRequiredFields.add(fieldName);
            record._invalidFields.add(fieldName);
        }
    }
    const isValid = !record._invalidFields.size;
    if (!isValid && displayNotification) {
        record._closeInvalidFieldsNotification =
            displayInvalidFieldNotification(record);
    }
    return isValid;
}

/**
 * Flag a field as invalid following user input that failed type
 * validation. Multi-edit mode handles selection-side effects: when
 * the record is part of a multi-edit selection and is not the one
 * the user is actively discarding, the dialog is surfaced, the record
 * is discarded, and the mode is forced back to readonly so the
 * multi-edit cohort stays coherent.
 *
 * Invariant I2 (synchronous dirty mark) is preserved at the
 * class-method call site (``setInvalidField`` calls
 * ``this._markDirty()`` synchronously before delegating here), not
 * inside this helper. The helper assumes ``record.dirty`` has already
 * been set when the caller intended.
 *
 * Skips re-adding when the field is already in ``_invalidFields``
 * (idempotency), and respects the ``onWillSetInvalidField`` lifecycle
 * hook's veto.
 *
 * @param {RelationalRecord} record
 * @param {string} fieldName
 * @returns {Promise<void>}
 */
export async function setInvalidField(record, fieldName) {
    // NB: intentionally NOT awaited. The sole consumer of this hook is
    // synchronous, and introducing a microtask gap here changes the ordering
    // of invalid-field notifications in multi-edit (a single invalid commit
    // would surface two notifications). If an async veto consumer is ever
    // added, revisit both this call and that ordering together.
    const canProceed = record.model.hooks.lifecycle.onWillSetInvalidField(record, fieldName);
    if (canProceed === false) {
        return;
    }
    if (toRaw(record._invalidFields).has(fieldName)) {
        return;
    }
    record._invalidFields.add(fieldName);
    if (
        record.selected &&
        record.model.multiEdit &&
        record.model.root._recordToDiscard !== record
    ) {
        displayInvalidFieldNotification(record);
        await record.discard();
        record.switchMode("readonly");
    }
}

/**
 * Clear a single field's invalid flag — typically called by field
 * widgets after the user corrects an input that previously failed
 * type validation (e.g. domain editor accepting an edit). Does not
 * touch ``_unsetRequiredFields``: a field can be invalid AND unset
 * simultaneously; this helper only removes the invalid-input flag.
 *
 * @param {RelationalRecord} record
 * @param {string} fieldName
 */
export function resetFieldValidity(record, fieldName) {
    record._invalidFields.delete(fieldName);
}

/**
 * Bulk variant of {@link resetFieldValidity}: clear invalid flags for
 * an arbitrary number of field names. Used by ``_applyChanges`` to mark
 * changed fields as valid before re-running ``checkValidity`` in
 * ``removeInvalidOnly`` mode.
 *
 * @param {RelationalRecord} record
 * @param {...string} fieldNames
 */
export function removeInvalidFields(record, ...fieldNames) {
    for (const fieldName of fieldNames) {
        record._invalidFields.delete(fieldName);
    }
}

/**
 * Surface the "invalid fields" UI notification via the model's
 * ``hooks.ui.onDisplayInvalidFields`` hook. Returns the hook's close
 * callback so the caller (or a later ``discard`` / ``_setData``
 * lifecycle event) can dismiss the toast when the invalid state is
 * resolved.
 *
 * @param {RelationalRecord} record
 * @returns {() => void} close callback for the displayed notification
 */
export function displayInvalidFieldNotification(record) {
    return record.model.hooks.ui.onDisplayInvalidFields();
}
