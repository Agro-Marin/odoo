// @ts-check
/** @odoo-module native */

/** @module views/list/list_group_layout - Group header layout utilities for ListRenderer */

/** @import { Group } from "@web/model/relational_model/group" */
/** @typedef {import("@web/views/list/list_column_utils").Column} Column */

import { AGGREGATABLE_FIELD_TYPES } from "@web/model/relational_model/utils";

// When no aggregates are shown, the group name cell spans all data columns
// except the last one, which is reserved for the pager cell. This ensures
// the group header always renders 3 <th> elements: name, pager, config menu.

/**
 * Find the index of the first column that has an aggregate value.
 *
 * @param {Column[]} columns
 * @param {Object} fields
 * @param {Object} aggregates - group.aggregates or footer aggregates
 * @returns {number} index or -1
 */
export function getFirstAggregateIndex(columns, fields, aggregates) {
    return columns.findIndex(
        (col) =>
            col.name in aggregates &&
            col.widget !== "handle" &&
            AGGREGATABLE_FIELD_TYPES.includes(fields[col.name].type),
    );
}

/**
 * Find the index of the last column that has an aggregate value.
 *
 * @param {Column[]} columns
 * @param {Object} fields
 * @param {Object} aggregates
 * @returns {number} index or -1
 */
export function getLastAggregateIndex(columns, fields, aggregates) {
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
 * Get the slice of columns between first and last aggregate (inclusive).
 *
 * @param {Column[]} columns
 * @param {Object} fields
 * @param {Object} aggregates
 * @returns {Column[]}
 */
export function getAggregateColumns(columns, fields, aggregates) {
    const firstIndex = getFirstAggregateIndex(columns, fields, aggregates);
    const lastIndex = getLastAggregateIndex(columns, fields, aggregates);
    return columns.slice(firstIndex, lastIndex + 1);
}

/**
 * Compute the colspan for the group name cell (first cell in a group header row).
 *
 * @param {Column[]} columns
 * @param {Object} fields
 * @param {Object} aggregates
 * @param {{ hasSelectors: boolean }} options
 * @returns {number}
 */
export function getGroupNameCellColSpan(columns, fields, aggregates, { hasSelectors }) {
    const firstAggregateIndex = getFirstAggregateIndex(columns, fields, aggregates);
    let colspan;
    if (firstAggregateIndex > -1) {
        colspan = firstAggregateIndex;
    } else if (columns.length > 1) {
        // Reserve 1 column for the pager <th> so the header has 3 cells
        colspan = columns.length - 1;
    } else {
        // With only 1 column, span it fully (pager cell hidden via colspan 0)
        colspan = columns.length;
    }
    if (hasSelectors) {
        colspan++;
    }
    return colspan;
}

/**
 * Compute the colspan for the group pager cell (last cell in a group header row).
 *
 * @param {Column[]} columns
 * @param {Object} fields
 * @param {Object} aggregates
 * @param {{ hasOpenFormViewColumn: boolean }} options
 * @returns {number}
 */
export function getGroupPagerCellColspan(
    columns,
    fields,
    aggregates,
    { hasOpenFormViewColumn },
) {
    const lastAggregateIndex = getLastAggregateIndex(columns, fields, aggregates);
    let colspan;
    if (lastAggregateIndex > -1) {
        colspan = columns.length - lastAggregateIndex - 1;
        if (hasOpenFormViewColumn) {
            colspan++;
        }
    } else if (columns.length > 1) {
        // When no aggregates and 2+ columns, reserve 1 column for the pager cell
        colspan = 1;
        if (hasOpenFormViewColumn) {
            colspan++;
        }
    } else {
        // With only 1 column and no aggregates, hide the pager cell
        colspan = 0;
    }
    return colspan;
}

/**
 * Recursively count visible records in a (possibly nested) group.
 *
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
