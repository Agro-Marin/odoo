// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_value_transforms */

import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";

import { parseServerValue } from "./field_values.js";

/** @import { RecordContract } from "@web/model/relational_model/record_contract" */

/**
 * @param {string} fieldType
 * @param {any} value
 * @returns {any}
 */
export function formatServerValue(fieldType, value) {
    return registry.category("serializers").get(fieldType, (v) => v)(value);
}

registry
    .category("serializers")
    .add("date", (value) => (value ? serializeDate(value) : false))
    .add("datetime", (value) => (value ? serializeDateTime(value) : false))
    .add("char", (value) => (value !== "" ? value : false))
    .add("text", (value) => (value !== "" ? value : false))
    .add("html", (value) => (value?.length ? value : false))
    .add("many2one", (value) => (value ? value.id : false))
    .add("many2one_reference", (value) => (value ? value.resId : 0))
    .add("reference", (value) =>
        value?.resModel && value.resId ? `${value.resModel},${value.resId}` : false,
    )
    .add("properties", (value) => {
        if (!value) {
            return false;
        }
        return value.map((property) => {
            property = { ...property };
            for (const key of ["value", "default"]) {
                let val;
                if (property.type === "many2one") {
                    val = property[key] && [
                        property[key].id,
                        property[key].display_name,
                    ];
                } else if (
                    (property.type === "date" || property.type === "datetime") &&
                    typeof property[key] === "string"
                ) {
                    val = property[key];
                } else if (property[key] !== undefined) {
                    val = formatServerValue(property.type, property[key]);
                }
                property[key] = val;
            }
            return property;
        });
    });

/**
 * @param {string[]} fieldNames
 * @param {Object} fields
 * @returns {Record<string, unknown>}
 */
export function getDefaultValues(fieldNames, fields) {
    /** @type {Record<string, unknown>} */
    const defaultValues = {};
    for (const fieldName of fieldNames) {
        switch (fields[fieldName].type) {
            case "integer":
            case "float":
            case "monetary":
                defaultValues[fieldName] = fieldName === "id" ? false : 0;
                break;
            case "one2many":
            case "many2many":
                defaultValues[fieldName] = [];
                break;
            default:
                defaultValues[fieldName] = false;
        }
    }
    return defaultValues;
}

/**
 * @param {Object} values
 * @param {Object} activeFields
 * @param {Object} fields
 * @returns {Object}
 */
export function getTextValues(values, activeFields, fields) {
    const textValues = {};
    for (const fieldName of Object.keys(values)) {
        if (!activeFields[fieldName]) {
            continue;
        }
        if (["char", "text", "html"].includes(fields[fieldName].type)) {
            textValues[fieldName] = values[fieldName];
        }
    }
    return textValues;
}

/**
 * @param {Object} data
 * @param {Object} fields
 * @param {Object} textValues
 * @param {number|false} resId
 * @returns {{ withVirtualIds: Object, withoutVirtualIds: Object }}
 */
export function computeDataContext(data, fields, textValues, resId) {
    const dataContext = {};
    const x2manyDataContext = {
        withVirtualIds: {},
        withoutVirtualIds: {},
    };
    for (const fieldName of Object.keys(data)) {
        const value = data[fieldName];
        const field = fields[fieldName];
        if (field.relatedPropertyField) {
            continue;
        }
        if (["char", "text", "html"].includes(field.type)) {
            dataContext[fieldName] = textValues[fieldName];
        } else if (field.type === "one2many" || field.type === "many2many") {
            x2manyDataContext.withVirtualIds[fieldName] = value.currentIds;
            x2manyDataContext.withoutVirtualIds[fieldName] = value.currentIds.filter(
                (id) => typeof id === "number",
            );
        } else if (value && field.type === "date") {
            dataContext[fieldName] = serializeDate(value);
        } else if (value && field.type === "datetime") {
            dataContext[fieldName] = serializeDateTime(value);
        } else if (value && field.type === "many2one") {
            dataContext[fieldName] = value.id;
        } else if (value && field.type === "many2one_reference") {
            dataContext[fieldName] = value.resId;
        } else if (value && field.type === "reference") {
            dataContext[fieldName] = `${value.resModel},${value.resId}`;
        } else if (field.type === "properties") {
            dataContext[fieldName] = value.filter(
                (property) => !property.definition_deleted,
            );
        } else {
            dataContext[fieldName] = value;
        }
    }
    dataContext.id = resId || false;
    return {
        withVirtualIds: { ...dataContext, ...x2manyDataContext.withVirtualIds },
        withoutVirtualIds: {
            ...dataContext,
            ...x2manyDataContext.withoutVirtualIds,
        },
    };
}

/**
 * @param {RecordContract} record
 * @param {Object} serverValues
 * @param {Object} [options]
 * @param {Object} [options.currentValues]
 * @param {Object<string, Object>} [options.orderBys]
 * @returns {Object}
 */
export function parseServerValues(
    record,
    serverValues,
    { currentValues, orderBys } = {},
) {
    /** @type {Record<string, any>} */
    const parsedValues = {};
    if (!serverValues) {
        return parsedValues;
    }
    for (const fieldName of Object.keys(serverValues)) {
        const value = serverValues[fieldName];
        if (!record.activeFields[fieldName]) {
            continue;
        }
        const field = record.fields[fieldName];
        if (field.type === "one2many" || field.type === "many2many") {
            let staticList =
                /** @type {import("./static_list").StaticList | undefined} */ (
                    currentValues?.[fieldName]
                );
            const listValue = /** @type {any[]} */ (value);
            const valueIsCommandList = listValue.length && Array.isArray(listValue[0]);
            if (!staticList) {
                let data = valueIsCommandList ? [] : listValue;
                if (data.length && typeof data[0] === "number") {
                    data = data.map((resId) => ({ id: resId }));
                }
                staticList = record._createStaticListDatapoint(
                    /** @type {Array<{id: number, [key: string]: any}>} */ (data),
                    fieldName,
                    { orderBys },
                );
                if (valueIsCommandList && staticList) {
                    staticList._applyInitialCommands(listValue);
                }
            } else if (valueIsCommandList && staticList) {
                staticList.stageCommands(listValue);
            }
            parsedValues[fieldName] = staticList;
        } else {
            parsedValues[fieldName] = parseServerValue(field, value);
            if (field.type === "properties") {
                const parent =
                    /** @type {{ id?: number; display_name?: string } | false | undefined} */ (
                        serverValues[/** @type {string} */ (field.definition_record)]
                    );
                Object.assign(
                    parsedValues,
                    record._processProperties(
                        parsedValues[fieldName],
                        fieldName,
                        parent,
                        currentValues,
                    ),
                );
            }
        }
    }
    return parsedValues;
}
