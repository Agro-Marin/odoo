// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_validator */

import { toRaw } from "@odoo/owl";

import { isX2Many } from "./field_context.js";
import { listId } from "./static_list_utils.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * @param {Object} activeFields
 * @param {Object} fields
 * @param {Object} data
 * @param {Object} callbacks
 * @param {(fieldName: string) => boolean} callbacks.isInvisible
 * @param {(fieldName: string) => boolean} callbacks.isRequired
 * @param {(fieldName: string, list: Object) => boolean} callbacks.isChildListValid
 * @returns {Set<string>}
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
                        (/** @type {any} */ propertyDefinition) =>
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

/**
 * Drop invalidity the user has no way to clear.
 *
 * {@link findUnsetRequiredFields} has always skipped invisible fields, so
 * required-driven invalidity is already "invisible implies not blocking". Field
 * widgets mark their own invalidity through {@link setInvalidField} -- an
 * unparseable date or number, a malformed domain -- and that half was never
 * re-examined once set. A field hidden by a modifier AFTER the user typed into
 * it therefore kept blocking every save, behind a notification naming a field
 * that is not on screen: the form could only be escaped by discarding.
 *
 * Nothing unsafe is written by clearing it. A parse failure means the widget
 * never handed the value to the record, so what gets saved is the last value
 * that did parse -- and the server validates regardless.
 *
 * @param {RelationalRecord} record
 */
function pruneUnreachableInvalidFields(record) {
    for (const fieldName of [...toRaw(record._invalidFields)]) {
        if (!(fieldName in record.activeFields) || record._isInvisible(fieldName)) {
            record._invalidFields.delete(fieldName);
            record._unsetRequiredFields.delete(fieldName);
        }
    }
}

/**
 * @param {RelationalRecord} record
 * @param {{ silent?: boolean, displayNotification?: boolean, removeInvalidOnly?: boolean, scopedFields?: Set<string> }} [options]
 * @returns {boolean}
 */
export function checkValidity(
    record,
    { silent, displayNotification, removeInvalidOnly, scopedFields } = {},
) {
    // `silent` means "answer the question without touching state", so the prune
    // is skipped there along with every other mutation below.
    if (!silent) {
        pruneUnreachableInvalidFields(record);
    }
    const callbacks = {
        isInvisible: (/** @type {any} */ fieldName) => record._isInvisible(fieldName),
        isRequired: (/** @type {any} */ fieldName) => record._isRequired(fieldName),
        isChildListValid: (/** @type {any} */ _fieldName, /** @type {any} */ list) => {
            const membership = new Set(list.currentIds);
            return list.cachedRecords.every((/** @type {any} */ r) => {
                if (!membership.has(listId(r))) {
                    return true;
                }
                if (!r.hasPendingChanges) {
                    return true;
                }
                if (removeInvalidOnly && r.isValid) {
                    return true;
                }
                return r._checkValidity({ silent, removeInvalidOnly });
            });
        },
    };

    if (removeInvalidOnly) {
        const candidates = [];
        for (const fieldName of Array.from(record._unsetRequiredFields)) {
            if (!(fieldName in record.activeFields)) {
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
            record.setInvalidFieldsNotification(
                displayInvalidFieldNotification(record),
            );
        }
        return isValid;
    }

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
        record.setInvalidFieldsNotification(displayInvalidFieldNotification(record));
    }
    return isValid;
}

/**
 * @param {RelationalRecord} record
 * @param {string} fieldName
 * @returns {Promise<void>}
 */
export async function setInvalidField(record, fieldName) {
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
        !record.model.root._isRecordToDiscard?.(record)
    ) {
        displayInvalidFieldNotification(record);
        await record.discard();
        record.switchMode("readonly");
    }
}

/**
 * @param {RelationalRecord} record
 * @param {string} fieldName
 */
export function resetFieldValidity(record, fieldName) {
    record._invalidFields.delete(fieldName);
}

/**
 * @param {RelationalRecord} record
 * @param {...string} fieldNames
 */
export function removeInvalidFields(record, ...fieldNames) {
    for (const fieldName of fieldNames) {
        record._invalidFields.delete(fieldName);
    }
}

/**
 * @param {RelationalRecord} record
 * @returns {() => void}
 */
export function displayInvalidFieldNotification(record) {
    return record.model.hooks.ui.onDisplayInvalidFields();
}
