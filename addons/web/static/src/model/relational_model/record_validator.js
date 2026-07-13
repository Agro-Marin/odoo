// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_validator - Validation orchestration: unset-required scan, invalid-field set management, and notification routing */

/**
 * Validation logic for Record field values. {@link findUnsetRequiredFields} is
 * a pure scan (exported for unit testing); the orchestration helpers below
 * (checkValidity, setInvalidField, resetFieldValidity, removeInvalidFields,
 * displayInvalidFieldNotification) take the RelationalRecord as first arg
 * and mutate its `_invalidFields` / `_unsetRequiredFields` /
 * `_closeInvalidFieldsNotification` state. RelationalRecord's own methods
 * remain thin delegators so sibling files (dynamic_list.js, record_save.js,
 * static_list.js) can still call `record._checkValidity(...)`.
 */

import { toRaw } from "@odoo/owl";

import { isX2Many } from "./field_context.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Determine which required fields are unset or invalid (empty string for
 * html, zero count for x2many, etc.), skipping invisible and
 * property-derived fields.
 *
 * @param {Object} activeFields
 * @param {Object} fields - field definitions
 * @param {Object} data - current record data
 * @param {Object} callbacks
 * @param {(fieldName: string) => boolean} callbacks.isInvisible
 * @param {(fieldName: string) => boolean} callbacks.isRequired
 * @param {(fieldName: string, list: Object) => boolean} callbacks.isChildListValid
 *     Validates x2many child records (field name + StaticList datapoint);
 *     true if all children are valid.
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
                if (
                    isRequired(fieldName) &&
                    (!data[fieldName] || data[fieldName].length === 0)
                ) {
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

// Orchestration helpers (mutate `record._invalidFields` /
// `record._unsetRequiredFields` / `record._closeInvalidFieldsNotification`)

/**
 * Run validation on a record and update its invalid-field state in place.
 * Optionally surface a UI notification when invalid fields are detected.
 *
 * Three mutually exclusive modes:
 *   - **silent**: scan only, no mutation; returns whether no required field
 *     is unset.
 *   - **removeInvalidOnly**: prune stale entries from `_unsetRequiredFields`
 *     (and matching `_invalidFields`) without touching invalid-input flags
 *     set by {@link setInvalidField}. Used by `_applyChanges` to re-validate
 *     after edits. Since it only prunes, the scan is scoped to
 *     currently-flagged fields (further narrowed by `scopedFields` when
 *     given) — safe because unset-required status is per-field-local, and
 *     x2many fields are always re-checked (a child's validity can depend on
 *     an invisible `parent.*` reference).
 *   - **default**: replace `_unsetRequiredFields` with a fresh full scan;
 *     invalid-input flags (set via {@link setInvalidField}) survive since
 *     they live in `_invalidFields` but aren't tracked there.
 *
 * Child x2many validation recurses through each child's own
 * `_checkValidity`, so per-class overrides still apply.
 *
 * @param {RelationalRecord} record
 * @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean, scopedFields?: Set<string> }} [options]
 * @returns {boolean} `true` when the record has no invalid fields after the scan
 */
export function checkValidity(
    record,
    { silent, displayNotification, removeInvalidOnly, scopedFields } = {},
) {
    const callbacks = {
        isInvisible: (fieldName) => record._isInvisible(fieldName),
        isRequired: (fieldName) => record._isRequired(fieldName),
        isChildListValid: (_fieldName, list) =>
            list.records.every((r) => {
                if (!r.dirty) {
                    return true;
                }
                // removeInvalidOnly only prunes; an already-valid child can't
                // become invalid on this path, so skip it — turns
                // re-validation from O(dirtyRows × rowFields) into
                // O(dirtyRows) plus a rescan of only the still-invalid
                // row(s). silent/default modes need the full rescan.
                if (removeInvalidOnly && r.isValid) {
                    return true;
                }
                return r._checkValidity({ silent, removeInvalidOnly });
            }),
    };

    if (removeInvalidOnly) {
        // Prune-only, scoped path: only already-flagged fields can be
        // pruned, and only those whose status could have changed
        // (scopedFields, or any x2many — conservative for parent.*
        // dependencies) need re-evaluation.
        const candidates = [];
        for (const fieldName of Array.from(record._unsetRequiredFields)) {
            if (!(fieldName in record.activeFields)) {
                // No longer active: the full scan (which only iterates
                // activeFields) could never re-flag it, so preserve that pruning.
                record._unsetRequiredFields.delete(fieldName);
                record._invalidFields.delete(fieldName);
                continue;
            }
            const field = record.fields[fieldName];
            const isX2many = isX2Many(field);
            if (scopedFields && !scopedFields.has(fieldName) && !isX2many) {
                continue;
            }
            candidates.push(fieldName);
        }
        if (candidates.length) {
            const restrictedActiveFields = {};
            for (const fieldName of candidates) {
                restrictedActiveFields[fieldName] = record.activeFields[fieldName];
            }
            const freshUnset = findUnsetRequiredFields(
                restrictedActiveFields,
                record.fields,
                record.data,
                callbacks,
            );
            for (const fieldName of candidates) {
                if (!freshUnset.has(fieldName)) {
                    record._unsetRequiredFields.delete(fieldName);
                    record._invalidFields.delete(fieldName);
                }
            }
        }
        const isValid = !record._invalidFields.size;
        if (!isValid && displayNotification) {
            record._closeInvalidFieldsNotification =
                displayInvalidFieldNotification(record);
        }
        return isValid;
    }

    // silent / default: full scan over all active fields.
    const unsetRequiredFields = findUnsetRequiredFields(
        record.activeFields,
        record.fields,
        record.data,
        callbacks,
    );

    if (silent) {
        return !unsetRequiredFields.size;
    }

    for (const fieldName of Array.from(record._unsetRequiredFields)) {
        record._invalidFields.delete(fieldName);
    }
    record._unsetRequiredFields.clear();
    for (const fieldName of unsetRequiredFields) {
        record._unsetRequiredFields.add(fieldName);
        record._invalidFields.add(fieldName);
    }
    const isValid = !record._invalidFields.size;
    if (!isValid && displayNotification) {
        record._closeInvalidFieldsNotification =
            displayInvalidFieldNotification(record);
    }
    return isValid;
}

/**
 * Flag a field invalid after user input failed type validation. In
 * multi-edit, if the record is part of the selection and isn't the one
 * being actively discarded, surfaces the notification, discards the
 * record, and forces it back to readonly so the cohort stays coherent.
 *
 * Invariant I2 (synchronous dirty mark) is preserved at the class-method
 * call site, not here — this helper assumes `record.dirty` is already set.
 * Idempotent (no-op if already invalid) and respects the
 * `onWillSetInvalidField` lifecycle hook's veto.
 *
 * @param {RelationalRecord} record
 * @param {string} fieldName
 * @returns {Promise<void>}
 */
export async function setInvalidField(record, fieldName) {
    // NB: intentionally NOT awaited — the sole consumer is synchronous, and
    // awaiting here would reorder invalid-field notifications in multi-edit
    // (a single invalid commit would surface two). Revisit if an async veto
    // consumer is ever added.
    const canProceed = record.model.hooks.lifecycle.onWillSetInvalidField(
        record,
        fieldName,
    );
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
        // narrow list-owned interface — don't read root._recordToDiscard
        // directly (no-op when the root isn't a DynamicList)
        !record.model.root._isRecordToDiscard?.(record)
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
