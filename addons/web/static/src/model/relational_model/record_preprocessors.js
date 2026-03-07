// @ts-check

/** @module @web/model/relational_model/record_preprocessors - Field change preprocessing extracted from RelationalRecord */

/**
 * Preprocessing logic for field changes before they are applied to a record.
 *
 * Handles many2one completion (name_create / webRead), many2one_reference,
 * reference, x2many commands, properties expansion, and html markup.
 * Receives the RelationalRecord instance as first argument (delegation pattern).
 */

import { markup } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { x2ManyCommands } from "./commands";
import { getBasicEvalContext, getFieldContext } from "./field_context";
import { getFieldsSpec } from "./field_spec";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Complete a many2one value: fetch display_name if missing, or create via name_create.
 * @param {RelationalRecord} record
 * @param {{ id?: number, display_name?: string }} value
 * @param {string} fieldName
 * @param {string} resModel
 * @returns {Promise<false | { id: number, display_name: string }>}
 */
async function completeMany2OneValue(record, value, fieldName, resModel) {
    const resId = value.id;
    const displayName = value.display_name;
    if (!resId && !displayName) {
        return false;
    }
    const context = getFieldContext(record, fieldName);
    if (!resId && displayName !== undefined) {
        const pair = await record.model.orm.call(
            resModel,
            "name_create",
            [displayName],
            { context },
        );
        return pair && { id: pair[0], display_name: pair[1] };
    }
    if (resId && displayName === undefined) {
        const fieldSpec = { display_name: {} };
        if (record.activeFields[fieldName].related) {
            Object.assign(
                fieldSpec,
                getFieldsSpec(
                    record.activeFields[fieldName].related.activeFields,
                    record.activeFields[fieldName].related.fields,
                    getBasicEvalContext(record.config),
                ),
            );
        }
        const kwargs = { context, specification: fieldSpec };
        const records = await record.model.orm.webRead(resModel, [resId], kwargs);
        return records[0];
    }
    return /** @type {{ id: number, display_name: string }} */ (value);
}

/**
 * Preprocess many2one field changes — complete values with display_name or name_create.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export async function preprocessMany2oneChanges(record, changes) {
    const proms = Object.entries(changes)
        .filter(([fieldName]) => record.fields[fieldName].type === "many2one")
        .map(async ([fieldName, value]) => {
            if (!value) {
                changes[fieldName] = false;
            } else if (!record.activeFields[fieldName]) {
                changes[fieldName] = value;
            } else {
                const relation = record.fields[fieldName].relation;
                return completeMany2OneValue(record, value, fieldName, relation).then(
                    (v) => {
                        changes[fieldName] = v;
                    },
                );
            }
        });
    return Promise.all(proms);
}

/**
 * Preprocess many2one_reference field changes.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export async function preprocessMany2OneReferenceChanges(record, changes) {
    const proms = Object.entries(changes)
        .filter(
            ([fieldName]) => record.fields[fieldName].type === "many2one_reference",
        )
        .map(async ([fieldName, value]) => {
            if (!value) {
                changes[fieldName] = false;
            } else if (typeof value === "number") {
                // Many2OneReferenceInteger field only manipulates the id
                changes[fieldName] = { resId: value };
            } else {
                const relation = record.data[record.fields[fieldName].model_field];
                return completeMany2OneValue(
                    record,
                    { id: value.resId, display_name: value.displayName },
                    fieldName,
                    relation,
                ).then((v) => {
                    const m2o =
                        /** @type {{ id: number, display_name: string }} */ (v);
                    changes[fieldName] = {
                        resId: m2o.id,
                        displayName: m2o.display_name,
                    };
                });
            }
        });
    return Promise.all(proms);
}

/**
 * Preprocess reference field changes.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export async function preprocessReferenceChanges(record, changes) {
    const proms = Object.entries(changes)
        .filter(([fieldName]) => record.fields[fieldName].type === "reference")
        .map(async ([fieldName, value]) => {
            if (!value) {
                changes[fieldName] = false;
            } else {
                return completeMany2OneValue(
                    record,
                    { id: value.resId, display_name: value.displayName },
                    fieldName,
                    value.resModel,
                ).then((v) => {
                    const m2o =
                        /** @type {{ id: number, display_name: string }} */ (v);
                    changes[fieldName] = {
                        resId: m2o.id,
                        resModel: value.resModel,
                        displayName: m2o.display_name,
                    };
                });
            }
        });
    return Promise.all(proms);
}

/**
 * Preprocess x2many field changes — apply commands to the static list.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export async function preprocessX2manyChanges(record, changes) {
    for (const [fieldName, value] of Object.entries(changes)) {
        if (
            record.fields[fieldName].type !== "one2many" &&
            record.fields[fieldName].type !== "many2many"
        ) {
            continue;
        }
        const list = record.data[fieldName];
        for (const command of value) {
            switch (command[0]) {
                case x2ManyCommands.SET:
                    await list._replaceWith(command[2]);
                    break;
                default:
                    await list._applyCommands([command]);
            }
        }
        changes[fieldName] = list;
    }
}

/**
 * Preprocess properties field changes — expand property values.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export function preprocessPropertiesChanges(record, changes) {
    for (const [fieldName, value] of Object.entries(changes)) {
        const field = record.fields[fieldName];
        if (field.type === "properties") {
            const parent =
                changes[field.definition_record] ||
                record.data[field.definition_record];
            Object.assign(
                changes,
                record._processProperties(value, fieldName, parent, record.data),
            );
        } else if (field?.relatedPropertyField) {
            const [propertyFieldName, propertyName] = field.name.split(".");
            const propertiesData = record.data[propertyFieldName] || [];
            if (
                !propertiesData.find((property) => property.name === propertyName)
            ) {
                // try to change the value of a properties that has a different parent
                record.model.hooks.onDisplayPropertyWarning(
                    _t(
                        "This record belongs to a different parent so you can not change this property.",
                    ),
                );
                return;
            }
            changes[propertyFieldName] = propertiesData.map((property) =>
                property.name === propertyName ? { ...property, value } : property,
            );
        }
    }
}

/**
 * Preprocess html field changes — wrap values with markup.
 * @param {RelationalRecord} record
 * @param {Record<string, any>} changes
 */
export function preprocessHtmlChanges(record, changes) {
    for (const [fieldName, value] of Object.entries(changes)) {
        if (record.fields[fieldName].type === "html") {
            changes[fieldName] = value === false ? false : markup(value);
        }
    }
}
