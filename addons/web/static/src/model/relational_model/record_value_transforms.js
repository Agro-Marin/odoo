// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/record_value_transforms - Stateless value formatting, defaults, eval context extraction, and bulk server-value parsing */

/**
 * Value transformation functions for Record data.
 *
 * Most helpers (``formatServerValue``, ``getDefaultValues``,
 * ``getTextValues``, ``computeDataContext``) are pure and independently
 * testable.
 *
 * ``parseServerValues`` takes the RelationalRecord as its first argument
 * because it must call back into ``record``-owned protected methods that
 * hold per-instance state (``_createStaticListDatapoint``,
 * ``_processProperties``), accessed directly as ``record._X`` per the
 * convention in ``record_lifecycle.js`` / ``record_validator.js``. Tests
 * stub these by setting them on a mock record.
 */

import { serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";

import { parseServerValue } from "./field_values.js";

/** @import { RelationalRecord } from "@web/model/relational_model/record" */

/**
 * Format a JS field value back to server format.
 *
 * Inverse of `parseServerValue` (in utils.js). Handles all field types
 * including recursive property definitions.
 *
 * @param {string} fieldType
 * @param {any} value
 * @returns {any} server-formatted value
 */
export function formatServerValue(fieldType, value) {
    return registry.category("serializers").get(fieldType, (v) => v)(value);
}

/**
 * Per-type client→server value serializers, keyed by field type — the inverse
 * of the ``deserializers`` registry (`@web/model/relational_model/field_values`).
 *
 * Single source shared with the value codec (`@web/core/field_codec`): the
 * codec's ``serialize`` reads this same registry. Each entry is
 * ``(value) => serverValue``; types with no entry pass the value through
 * unchanged. Note the intentional read-rich/write-lean asymmetry vs the
 * deserializers (e.g. ``many2one`` reads ``[id, name]`` → ``{id, display_name}``
 * but writes back just the id) — the server only needs the id on write.
 */
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
                    // TO REMOVE: need refactoring PropertyField to use the same format as the server
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
 * Compute default values for fields that don't have data yet.
 *
 * @param {string[]} fieldNames
 * @param {Object} fields - field definitions
 * @returns {Object} default values keyed by field name
 */
export function getDefaultValues(fieldNames, fields) {
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
 * Extract text values for char, text, and html fields.
 *
 * These track the raw server values so the eval context distinguishes
 * between NULL (false) and empty string ("") for char/text/html fields.
 *
 * @param {Object} values - field values
 * @param {Object} activeFields
 * @param {Object} fields - field definitions
 * @returns {Object} text values keyed by field name
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
 * Build a data context suitable for Python eval expressions from record data.
 *
 * Returns two variants: one including virtual IDs (for attribute evaluation)
 * and one with only real database IDs (for server-bound contexts).
 *
 * @param {Object} data - record data (should be toRaw'd before passing)
 * @param {Object} fields - field definitions
 * @param {Object} textValues - text values for char/text/html fields
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
 * Parse a bag of server values into JS-shaped record values.
 *
 * Dispatch by field type:
 *   - **x2many**: build or reuse a StaticList via
 *     ``record._createStaticListDatapoint``. The server value may be a
 *     list of record objects (``[{id, name, ...}, ...]``), a list of
 *     bare ids (``[1, 2, 3]`` — converted to ``[{id: 1}, ...]``), or a
 *     list of x2many commands (``[[4, 1, 0], ...]``, detected via
 *     element 0) — applied through ``staticList._applyInitialCommands``
 *     (new list) or ``._applyCommands`` (existing, via ``currentValues``).
 *   - **properties**: parse via ``parseServerValue``, then
 *     ``record._processProperties`` splices the dynamic definitions
 *     into ``record.fields`` / ``activeFields`` and returns per-property
 *     values merged into the result.
 *   - **other**: delegate to ``parseServerValue(field, value)``.
 *
 * Skips fields not declared in ``record.activeFields`` (the server may
 * send more fields than the view subscribes to — e.g. the
 * ``definition_record`` companion of a properties field).
 *
 * Returns a plain object without assigning ``record._values`` — the
 * call sites in record.js own that assignment/``markRaw`` wrapping, to
 * preserve the three-layer state contract (``_values`` server-truth /
 * ``_changes`` user-edits / ``data`` merged).
 *
 * @param {RelationalRecord} record
 * @param {Object} serverValues - field-name → server-shape value
 * @param {Object} [options]
 * @param {Object} [options.currentValues] - existing parsed values
 *  (for x2many reuse / command-list application against an existing
 *  StaticList datapoint)
 * @param {Object<string, Object>} [options.orderBys] - default
 *  ``orderBy`` overrides per x2many field name; forwarded to newly-
 *  constructed StaticList datapoints
 * @returns {Object} parsed values keyed by field name
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
            // value can be a list of records or a list of commands (new record)
            const valueIsCommandList = listValue.length && Array.isArray(listValue[0]);
            if (!staticList) {
                let data = valueIsCommandList ? [] : listValue;
                if (data.length && typeof data[0] === "number") {
                    data = data.map((resId) => ({ id: resId }));
                }
                // ``data`` is either plain ids (mapped to ``{id}``), an
                // empty array (command-list path), or pre-shaped server
                // records — all valid shapes for the constructor.
                staticList = record._createStaticListDatapoint(
                    /** @type {Array<{id: number, [key: string]: any}>} */ (data),
                    fieldName,
                    { orderBys },
                );
                if (valueIsCommandList) {
                    staticList._applyInitialCommands(listValue);
                }
            } else if (valueIsCommandList) {
                // This call chain is synchronous (record._setData →
                // parseServerValues) — the possibly-async result is tracked
                // on the list so save/discard flows can sequence after it
                // and rejections are surfaced instead of floating.
                staticList._trackCommandsPromise(staticList._applyCommands(listValue));
            }
            parsedValues[fieldName] = staticList;
        } else {
            parsedValues[fieldName] = parseServerValue(field, value);
            if (field.type === "properties") {
                // ``definition_record`` names the parent field (m2o on the
                // record that defines the property set). The value at that
                // key is the parsed m2o value — ``{id, display_name}`` or
                // ``false`` if unset — see ``_processProperties`` which
                // reads ``parent?.id`` and ``parent?.display_name``.
                const parent =
                    /** @type {{ id?: number; display_name?: string } | false | undefined} */ (
                        serverValues[field.definition_record]
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
