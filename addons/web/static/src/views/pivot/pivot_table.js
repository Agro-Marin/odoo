// @ts-check
/** @odoo-module native */

/**
 * Turns in-memory pivot data (group trees, measurements) into row/column
 * arrays for rendering an HTML table: header rows with col-group hierarchy
 * and spans, body rows with cell values and indentation.
 *
 * @module pivot_table
 */

import { _t } from "@web/core/l10n/translation";

import { getLeafCounts } from "./pivot_group_tree.js";
import {
    getCellCurrency,
    getCellValue,
    getMeasuresRow,
    makeCellKey,
} from "./pivot_measurements.js";

/**
 * Header rows of the pivot table: the col group rows (per col groupby), then the measures row.
 *
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object[]}
 */
export function getTableHeaders(data, metaData) {
    const colGroupBys = metaData.fullColGroupBys;
    const height = colGroupBys.length + 1;
    const measureCount = metaData.activeMeasures.length;
    const leafCounts = getLeafCounts(data.colGroupTree);
    let headers = [];
    const measureColumns = [];

    // 1) generate col group rows (total row + one row for each col groupby)
    const colGroupRows = Array.from({ length: height }, () => []);
    // blank top left cell
    colGroupRows[0].push({
        height: height + 1,
        title: "",
        width: 1,
    });

    // col groupby cells with group values
    function generateTreeHeaders(tree) {
        const group = tree.root;
        const rowIndex = group.values.length;
        const row = colGroupRows[rowIndex];
        const groupId = [[], group.values];
        const isLeaf = !tree.directSubTrees.size;
        const leafCount = leafCounts[JSON.stringify(tree.root.values)];
        const cell = {
            groupId,
            height: isLeaf ? colGroupBys.length + 1 - rowIndex : 1,
            isLeaf,
            isFolded: isLeaf && colGroupBys.length > group.values.length,
            label:
                rowIndex === 0
                    ? undefined
                    : metaData.fields[colGroupBys[rowIndex - 1].split(":")[0]].string,
            title: group.labels.length ? group.labels.at(-1) : _t("Total"),
            width: leafCount * measureCount,
        };
        row.push(cell);
        if (isLeaf) {
            measureColumns.push(cell);
        }
        for (const subTree of tree.directSubTrees.values()) {
            generateTreeHeaders(subTree);
        }
    }

    generateTreeHeaders(data.colGroupTree);

    // blank top right cell for 'Total' group (if there is more than one leaf)
    if (leafCounts[JSON.stringify(data.colGroupTree.root.values)] > 1) {
        const groupId = [[], []];
        const totalTopRightCell = {
            groupId,
            height,
            title: "",
            width: measureCount,
        };
        colGroupRows[0].push(totalTopRightCell);
        measureColumns.push(totalTopRightCell);
    }
    headers = [...headers, ...colGroupRows];

    // 2) generate measures row
    const measuresRow = getMeasuresRow(measureColumns, metaData);
    headers.push(measuresRow);

    return headers;
}

/**
 * Body rows of the pivot table for a given tree.
 *
 * @param {Object} tree
 * @param {Object[]} columns
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object[]}
 */
export function getTableRows(tree, columns, data, metaData) {
    const rows = [];
    // Stringify each column's group values once per table build instead of
    // once per cell (rows × columns × 2 JSON.stringify otherwise).
    const columnKeys = columns.map((column) => JSON.stringify(column.groupId[1]));
    _collectTableRows(tree, columns, columnKeys, data, metaData, rows);
    return rows;
}

/**
 * Pre-order walk that pushes each tree node's row into a single shared
 * accumulator. Replaces the previous ``rows = [...rows, ...recurse()]`` which
 * re-copied the whole accumulated array at every node (O(N²) in tree size,
 * re-paid on every render / expand-all).
 *
 * @param {Object} tree
 * @param {Object[]} columns
 * @param {string[]} columnKeys stringified column group values, one per column
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object[]} rows accumulator, mutated in place
 */
function _collectTableRows(tree, columns, columnKeys, data, metaData, rows) {
    const group = tree.root;
    const rowGroupId = [group.values, []];
    const rowKey = JSON.stringify(group.values);
    const title = group.labels.length ? group.labels.at(-1) : _t("Total");
    const indent = group.labels.length;
    const isLeaf = !tree.directSubTrees.size;
    const rowGroupBys = metaData.fullRowGroupBys;

    const subGroupMeasurements = columns.map((column, columnIndex) => {
        const colGroupId = column.groupId;
        const groupIntersectionId = [rowGroupId[0], colGroupId[1]];
        const cellKey = makeCellKey(rowKey, columnKeys[columnIndex]);
        const measure = column.measure;

        const value = getCellValue(cellKey, measure, data);
        const currencyIds = getCellCurrency(cellKey, measure, data);

        return {
            groupId: groupIntersectionId,
            measure,
            value,
            currencyIds,
            isBold: !groupIntersectionId[0].length || !groupIntersectionId[1].length,
        };
    });

    rows.push({
        title,
        label:
            indent === 0
                ? undefined
                : metaData.fields[rowGroupBys[indent - 1].split(":")[0]].string,
        groupId: rowGroupId,
        indent,
        isLeaf,
        isFolded: isLeaf && rowGroupBys.length > group.values.length,
        subGroupMeasurements,
    });

    const subTreeKeys = tree.sortedKeys || [...tree.directSubTrees.keys()];
    for (const subTreeKey of subTreeKeys) {
        const subTree = tree.directSubTrees.get(subTreeKey);
        _collectTableRows(subTree, columns, columnKeys, data, metaData, rows);
    }
}
