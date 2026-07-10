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
 *
 *     Because this mode only ever *prunes* (never adds), the scan is
 *     scoped for performance: it re-evaluates only fields currently in
 *     ``_unsetRequiredFields`` — no other field can be pruned — and,
 *     when ``scopedFields`` is provided (from ``_applyChanges``), further
 *     skips flagged fields that provably cannot have changed status
 *     because neither their value nor any modifier they depend on was in
 *     the change set. x2many fields are always re-checked while flagged
 *     (a child's validity may depend on a ``parent.*`` reference that is
 *     invisible to the parent-level scope) — the isChildListValid
 *     recursion is itself scoped to avoid O(rows) cost (see below).
 *     Equivalence to the original full scan holds because unset-required
 *     status is per-field-local (own type/value/required/invisible, or —
 *     for x2many — its children).
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
 * @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean, scopedFields?: Set<string> }} [options]
 * @returns {boolean} ``true`` when the record has no invalid fields
 *  after the scan, ``false`` otherwise
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
                // ``removeInvalidOnly`` only prunes stale invalid flags; an
                // already-valid child has nothing to prune and cannot become
                // invalid on this path, so it can be skipped. This is what
                // turns the parent's post-commit re-validation from
                // O(dirtyRows × rowFields) into O(dirtyRows) cheap checks plus
                // a full re-scan of only the still-invalid row(s) — typically
                // just the row that was edited. ``silent`` and default modes
                // keep the exact full re-scan (they answer a fresh query /
                // may add newly-invalid fields respectively).
                if (removeInvalidOnly && r.isValid) {
                    return true;
                }
                return r._checkValidity({ silent, removeInvalidOnly });
            }),
    };

    if (removeInvalidOnly) {
        // Prune-only, scoped path. Only fields already flagged in
        // ``_unsetRequiredFields`` can be pruned, and of those only the ones
        // whose status could have changed (in ``scopedFields``, or any x2many
        // — conservative for ``parent.*`` child dependencies) need
        // re-evaluation. Everything else provably keeps its flagged status.
        const candidates = [];
        for (const fieldName of Array.from(record._unsetRequiredFields)) {
            if (!(fieldName in record.activeFields)) {
                // No longer an active field: the original full scan (which only
                // iterates activeFields) could never re-flag it, so it was
                // pruned. Preserve that exactly.
                record._unsetRequiredFields.delete(fieldName);
                record._invalidFields.delete(fieldName);
                continue;
            }
            const field = record.fields[fieldName];
            const isX2many =
                field && (field.type === "one2many" || field.type === "many2many");
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
