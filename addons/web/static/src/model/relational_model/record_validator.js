// @ts-check
/** @odoo-module native */

import { toRaw } from "@odoo/owl";
import { isX2Many } from "@web/core/field_types";

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
 * @param {RelationalRecord} record
 */
function pruneUnreachableInvalidFields(record) {
    for (const fieldName of [...toRaw(record.invalidFields)]) {
        if (!(fieldName in record.activeFields) || record.isFieldInvisible(fieldName)) {
            record.invalidFields.delete(fieldName);
            record.unsetRequiredFields.delete(fieldName);
        }
    }
}

/**
 * @param {RelationalRecord} record
 * @param {{ silent?: boolean, removeInvalidOnly?: boolean }} mode
 * @returns {{ isInvisible: (f: string) => boolean, isRequired: (f: string) => boolean,
 * isChildListValid: (f: string, list: any) => boolean }}
 */
function makeValidityCallbacks(record, { silent, removeInvalidOnly }) {
    return {
        isInvisible: (/** @type {any} */ fieldName) =>
            record.isFieldInvisible(fieldName),
        isRequired: (/** @type {any} */ fieldName) => record.isFieldRequired(fieldName),
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
                return r.checkValidityLocked({ silent, removeInvalidOnly });
            });
        },
    };
}

/**
 * @param {RelationalRecord} record
 * @param {ReturnType<typeof makeValidityCallbacks>} callbacks
 * @param {Set<string>} [scopedFields]
 * @returns {void}
 */
function releaseSatisfiedFields(record, callbacks, scopedFields) {
    const candidates = [];
    for (const fieldName of Array.from(record.unsetRequiredFields)) {
        if (!(fieldName in record.activeFields)) {
            record.unsetRequiredFields.delete(fieldName);
            record.invalidFields.delete(fieldName);
            continue;
        }
        if (
            scopedFields &&
            !scopedFields.has(fieldName) &&
            !isX2Many(record.fields[fieldName])
        ) {
            continue;
        }
        candidates.push(fieldName);
    }
    if (!candidates.length) {
        return;
    }
    /** @type {Record<string, any>} */
    const restrictedActiveFields = {};
    for (const fieldName of candidates) {
        restrictedActiveFields[fieldName] = record.activeFields[fieldName];
    }
    const stillUnset = findUnsetRequiredFields(
        restrictedActiveFields,
        record.fields,
        record.data,
        callbacks,
    );
    for (const fieldName of candidates) {
        if (!stillUnset.has(fieldName)) {
            record.unsetRequiredFields.delete(fieldName);
            record.invalidFields.delete(fieldName);
        }
    }
}

/**
 * @param {RelationalRecord} record
 * @param {Set<string>} unsetRequiredFields
 * @returns {void}
 */
function adoptUnsetRequiredFields(record, unsetRequiredFields) {
    for (const fieldName of Array.from(record.unsetRequiredFields)) {
        record.invalidFields.delete(fieldName);
    }
    record.unsetRequiredFields.clear();
    for (const fieldName of unsetRequiredFields) {
        record.unsetRequiredFields.add(fieldName);
        record.invalidFields.add(fieldName);
    }
}

/**
 * @param {RelationalRecord} record
 * @param {boolean | undefined} displayNotification
 * @returns {boolean}
 */
function reportValidity(record, displayNotification) {
    const isValid = !record.invalidFields.size;
    if (!isValid && displayNotification) {
        record.setInvalidFieldsNotification(displayInvalidFieldNotification(record));
    }
    return isValid;
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
    if (!silent) {
        pruneUnreachableInvalidFields(record);
    }
    const callbacks = makeValidityCallbacks(record, { silent, removeInvalidOnly });

    if (removeInvalidOnly) {
        releaseSatisfiedFields(record, callbacks, scopedFields);
        return reportValidity(record, displayNotification);
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
    adoptUnsetRequiredFields(record, unsetRequiredFields);
    return reportValidity(record, displayNotification);
}

/**
 * @param {RelationalRecord} record
 * @param {string} fieldName
 * @returns {Promise<void>}
 */
export async function setInvalidField(record, fieldName) {
    const canProceed = record.model.notifyLifecycleSync(
        "onWillSetInvalidField",
        record,
        fieldName,
    );
    if (canProceed === false) {
        return;
    }
    if (toRaw(record.invalidFields).has(fieldName)) {
        return;
    }
    record.invalidFields.add(fieldName);
    if (
        record.selected &&
        record.model.multiEdit &&
        !record.model.root.isRecordToDiscard?.(record)
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
    record.invalidFields.delete(fieldName);
}

/**
 * @param {RelationalRecord} record
 * @param {...string} fieldNames
 */
export function removeInvalidFields(record, ...fieldNames) {
    for (const fieldName of fieldNames) {
        record.invalidFields.delete(fieldName);
    }
}

/**
 * @param {RelationalRecord} record
 * @returns {() => void}
 */
export function displayInvalidFieldNotification(record) {
    return record.model.uiHooks.onDisplayInvalidFields();
}
