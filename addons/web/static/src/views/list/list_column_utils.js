// @ts-check
/** @odoo-module native */

/** @module views/list/list_column_utils - Column processing utilities for ListRenderer */

/** @import { DynamicList } from "@web/model/relational_model/dynamic_list" */
/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * @typedef {Object} Column
 * @property {string} type
 * @property {string} name
 * @property {string} id
 * @property {string} [label]
 * @property {string} [widget]
 * @property {boolean} [hasLabel]
 * @property {string} [optional]
 * @property {string} [classNames]
 * @property {string} [column_invisible]
 * @property {Object} [attrs]
 * @property {Object} [relatedPropertyField]
 */

import { getPropertyFieldInfo } from "@web/fields/field";
import { combineModifiers } from "@web/model/relational_model/utils";

/**
 * Memoized property-column expansions, keyed by the parent (arch) column
 * object. Expanded column objects must be referentially stable across
 * renders: they are compared by identity downstream (row-skipping via
 * `_toStableColumns`, per-column format-option memoization in
 * `view_utils.js`). Entries are validated against the identity of the
 * matched property field definitions (and their active fields), so a change
 * in the property definitions — which installs fresh field objects on the
 * list — rebuilds the expansion.
 *
 * @type {WeakMap<object, { fields: any[], activeFields: any[], columns: Column[] }>}
 */
const propertyColumnsCache = new WeakMap();

/**
 * Expand property fields into individual columns.
 *
 * @param {Column} column - a column of type "field" with a properties field
 * @param {DynamicList | StaticList} list
 * @returns {Column[]} expanded property columns
 */
export function getPropertyFieldColumns(column, list) {
    const propertyFields = /** @type {any[]} */ (Object.values(list.fields)).filter(
        (field) =>
            list.activeFields[field.name] &&
            field.relatedPropertyField &&
            field.relatedPropertyField.name === column.name &&
            field.type !== "separator",
    );
    const cached = propertyColumnsCache.get(column);
    if (
        cached &&
        cached.fields.length === propertyFields.length &&
        propertyFields.every(
            (field, i) =>
                field === cached.fields[i] &&
                list.activeFields[field.name] === cached.activeFields[i],
        )
    ) {
        return cached.columns;
    }
    const columns = propertyFields.map((propertyField) => {
        const activeField = list.activeFields[propertyField.name];
        return {
            ...getPropertyFieldInfo(propertyField),
            relatedPropertyField: activeField.relatedPropertyField,
            id: `${column.id}_${propertyField.name}`,
            column_invisible: combineModifiers(
                propertyField.column_invisible,
                column.column_invisible,
                "OR",
            ),
            classNames: column.classNames,
            optional: "hide",
            type: "field",
            hasLabel: true,
            label: propertyField.string,
            attrs: ["integer", "float"].includes(propertyField.type)
                ? { sum: propertyField.string }
                : {},
        };
    });
    propertyColumnsCache.set(column, {
        fields: propertyFields,
        activeFields: propertyFields.map((field) => list.activeFields[field.name]),
        columns,
    });
    return columns;
}

/**
 * Process all columns, expanding properties fields into individual columns.
 *
 * @param {Column[]} allColumns
 * @param {DynamicList | StaticList} list
 * @returns {Column[]}
 */
export function processAllColumns(allColumns, list) {
    return allColumns.flatMap((column) => {
        if (column.type === "field" && list.fields[column.name].type === "properties") {
            return getPropertyFieldColumns(column, list);
        } else {
            return [column];
        }
    });
}
