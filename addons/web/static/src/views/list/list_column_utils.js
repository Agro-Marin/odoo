// @ts-check
/** @odoo-module native */

/** @import { DynamicList } from "@web/model/relational_model/dynamic_list" */
/** @import { StaticList } from "@web/model/relational_model/static_list" */

/**
 * @typedef {{
 * type: string;
 * name: string;
 * id: string;
 * label?: string;
 * widget?: string;
 * hasLabel?: boolean;
 * optional?: string;
 * classNames?: string;
 * column_invisible?: string | boolean;
 * attrs?: Record<string, string>;
 * relatedPropertyField?: Record<string, unknown>;
 * [key: string]: unknown;
 * }} Column
 */

import { getPropertyFieldInfo } from "@web/fields/field";
import { combineModifiers } from "@web/model/relational_model";

/**
 * @type {WeakMap<object, { fields: any[], activeFields: any[], columns: Column[] }>}
 */
const propertyColumnsCache = new WeakMap();

/**
 * @param {Column} column
 * @param {DynamicList | StaticList} list
 * @returns {Column[]}
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
            ...getPropertyFieldInfo(propertyField, "list"),
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
