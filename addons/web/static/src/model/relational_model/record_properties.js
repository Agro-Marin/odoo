// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_properties */

import { x2ManyCommands } from "@web/core/network/commands";
import { _t } from "@web/core/translation";

import { createPropertyActiveField } from "./field_metadata.js";
import { invalidateAggregateSpecs } from "./field_values.js";
import { invalidateModifierDependencies } from "./record_utils.js";

/** @import { RecordContract } from "@web/model/relational_model/record_contract" */

/**
 * Declared against the record CONTRACT rather than `RelationalRecord`: this
 * reads `fields`, `activeFields` and `_createStaticListDatapoint`, and saying so
 * makes reaching for a fourth member a typecheck failure. See
 * `record_contract.js`.
 *
 * @param {RecordContract} record
 * @param {Object[]} properties
 * @param {string} fieldName
 * @param {{ id?: number; display_name?: string } | false} parent
 * @param {Object} [currentValues={}]
 * @returns {Object}
 */
export function processProperties(
    record,
    properties,
    fieldName,
    parent,
    currentValues = {},
) {
    /** @type {Record<string, any>} */
    const data = {};

    const hasCurrentValues = Object.keys(currentValues).length > 0;
    for (const property of properties) {
        const propertyFieldName = `${fieldName}.${property.name}`;

        if (hasCurrentValues || !record.fields[propertyFieldName]) {
            record.fields[propertyFieldName] = {
                ...property,
                name: propertyFieldName,
                relatedPropertyField: {
                    name: fieldName,
                },
                propertyName: property.name,
                relation: property.comodel,
                sortable: !["many2one", "many2many", "tags"].includes(property.type),
            };
        }
        if (hasCurrentValues || !record.activeFields[propertyFieldName]) {
            record.activeFields[propertyFieldName] =
                createPropertyActiveField(property);
        }

        if (!record.activeFields[propertyFieldName].relatedPropertyField) {
            record.activeFields[propertyFieldName].relatedPropertyField = {
                name: fieldName,
                id: parent ? parent.id : undefined,
                displayName: parent ? parent.display_name : undefined,
            };
        }

        if (property.type === "many2many") {
            let staticList = currentValues[propertyFieldName];
            if (!staticList) {
                staticList = record._createStaticListDatapoint(
                    (property.value || []).map((rec) => ({
                        id: rec[0],
                        display_name: rec[1],
                    })),
                    propertyFieldName,
                );
            } else if (
                typeof staticList.stageCommands === "function" &&
                (Array.isArray(property.value) || property.value === false)
            ) {
                const target = property.value || [];
                const currentIds = new Set(staticList.currentIds);
                const targetIds = new Set(target.map((rec) => rec[0]));
                const commands = [];
                for (const id of currentIds) {
                    if (!targetIds.has(id)) {
                        commands.push(x2ManyCommands.unlink(id));
                    }
                }
                for (const rec of target) {
                    if (!currentIds.has(rec[0])) {
                        commands.push([
                            x2ManyCommands.LINK,
                            rec[0],
                            { id: rec[0], display_name: rec[1] },
                        ]);
                    }
                }
                if (commands.length) {
                    staticList.stageCommands(commands);
                }
            }
            data[propertyFieldName] = staticList;
        } else if (property.type === "many2one") {
            data[propertyFieldName] =
                property.value && property.value.display_name === null
                    ? {
                          id: property.value.id,
                          display_name: _t("No Access"),
                      }
                    : property.value;
        } else {
            data[propertyFieldName] = property.value ?? false;
        }
    }

    if (properties.length) {
        invalidateModifierDependencies(record.activeFields);
        invalidateAggregateSpecs(record.fields);
    }

    return data;
}
