// @ts-check
/** @odoo-module native */

import { x2ManyCommands } from "@web/core/network/commands";
import { _t } from "@web/core/translation";
import { describePropertyDefinitionAsField } from "@web/model/property_fields";

import { createPropertyActiveField } from "./field_metadata.js";
import { invalidateAggregateSpecs } from "./field_values.js";
import { invalidateModifierDependencies } from "./record_utils.js";

/** @import { RecordContract } from "@web/model/relational_model/record_contract" */

/**
 * @param {Record<string, any>} property
 * @param {string} propertyFieldName
 * @returns {Record<string, any>}
 */
function describePropertyAsField(property, propertyFieldName) {
    return {
        ...describePropertyDefinitionAsField(propertyFieldName, property),
        sortable: !["many2one", "many2many", "tags"].includes(property.type),
    };
}

/**
 * @param {any} staticList
 * @param {[number, string][] | false} target
 * @returns {void}
 */
function reconcilePropertyList(staticList, target) {
    const rows = target || [];
    const currentIds = new Set(staticList.currentIds);
    const targetIds = new Set(rows.map((rec) => rec[0]));
    const commands = [];
    for (const id of currentIds) {
        if (!targetIds.has(id)) {
            commands.push(x2ManyCommands.unlink(id));
        }
    }
    for (const rec of rows) {
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

/**
 * @param {RecordContract} record
 * @param {Record<string, any>} property
 * @param {string} propertyFieldName
 * @param {Record<string, any>} currentValues
 * @returns {any}
 */
function buildPropertyValue(record, property, propertyFieldName, currentValues) {
    if (property.type === "many2many") {
        const staticList = currentValues[propertyFieldName];
        if (!staticList) {
            return record._createStaticListDatapoint(
                (property.value || []).map((/** @type {[number, string]} */ rec) => ({
                    id: rec[0],
                    display_name: rec[1],
                })),
                propertyFieldName,
            );
        }
        if (
            typeof staticList.stageCommands === "function" &&
            (Array.isArray(property.value) || property.value === false)
        ) {
            reconcilePropertyList(staticList, property.value);
        }
        return staticList;
    }
    if (property.type === "many2one") {
        return property.value && property.value.display_name === null
            ? { id: property.value.id, display_name: _t("No Access") }
            : property.value;
    }
    return property.value ?? false;
}

/**
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

    for (const property of /** @type {Record<string, any>[]} */ (properties)) {
        const propertyFieldName = `${fieldName}.${property.name}`;

        if (hasCurrentValues || !record.fields[propertyFieldName]) {
            record.fields[propertyFieldName] = describePropertyAsField(
                property,
                propertyFieldName,
            );
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

        data[propertyFieldName] = buildPropertyValue(
            record,
            property,
            propertyFieldName,
            currentValues,
        );
    }

    if (properties.length) {
        invalidateModifierDependencies(record.activeFields);
        invalidateAggregateSpecs(record.fields);
    }

    return data;
}
