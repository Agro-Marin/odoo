// @ts-check
/** @odoo-module native */

/** @import { Group } from "@web/model/relational_model/group" */
/** @typedef {import("@web/views/list/list_column_utils").Column} Column */

import { AGGREGATABLE_FIELD_TYPES } from "@web/model/relational_model/utils";

/**
 * @param {Column[]} columns
 * @param {Record<string, any>} fields
 * @param {Record<string, any>} aggregates
 * @returns {number}
 */
function getFirstAggregateIndex(columns, fields, aggregates) {
    return columns.findIndex(
        (col) =>
            col.name in aggregates &&
            col.widget !== "handle" &&
            AGGREGATABLE_FIELD_TYPES.includes(fields[col.name].type),
    );
}

/**
 * @param {Column[]} columns
 * @param {Record<string, any>} fields
 * @param {Record<string, any>} aggregates
 * @returns {number}
 */
function getLastAggregateIndex(columns, fields, aggregates) {
    const reversedColumns = columns.toReversed();
    const index = reversedColumns.findIndex(
        (col) =>
            col.name in aggregates &&
            col.widget !== "handle" &&
            AGGREGATABLE_FIELD_TYPES.includes(fields[col.name].type),
    );
    return index > -1 ? columns.length - index - 1 : -1;
}

/**
 * @param {Column[]} columns
 * @param {Record<string, any>} fields
 * @param {Object} aggregates
 * @returns {Column[]}
 */
export function getAggregateColumns(columns, fields, aggregates) {
    const firstIndex = getFirstAggregateIndex(columns, fields, aggregates);
    const lastIndex = getLastAggregateIndex(columns, fields, aggregates);
    return columns.slice(firstIndex, lastIndex + 1);
}

/**
 * @param {Column[]} columns
 * @param {Record<string, any>} fields
 * @param {Object} aggregates
 * @param {{ hasSelectors: boolean }} options
 * @returns {number}
 */
export function getGroupNameCellColSpan(columns, fields, aggregates, { hasSelectors }) {
    const firstAggregateIndex = getFirstAggregateIndex(columns, fields, aggregates);
    let colspan = firstAggregateIndex > -1 ? firstAggregateIndex : columns.length;
    if (hasSelectors) {
        colspan++;
    }
    return colspan;
}

/**
 * @param {Column[]} columns
 * @param {Record<string, any>} fields
 * @param {Object} aggregates
 * @param {{ hasOpenFormViewColumn?: boolean }} [options]
 * @returns {number}
 */
export function getGroupPagerCellColspan(
    columns,
    fields,
    aggregates,
    { hasOpenFormViewColumn } = {},
) {
    const lastIndex = getLastAggregateIndex(columns, fields, aggregates);
    let colspan = lastIndex > -1 ? columns.length - lastIndex - 1 : 0;
    if (hasOpenFormViewColumn) {
        colspan++;
    }
    return colspan;
}

/**
 * @param {Group} group
 * @returns {number}
 */
export function countRecordsInGroup(group) {
    if (group.isFolded) {
        return 0;
    } else if (group.list.isGrouped) {
        let count = 0;
        for (const gr of group.list.groups) {
            count += countRecordsInGroup(gr);
        }
        return count;
    } else {
        return group.list.records.length;
    }
}
