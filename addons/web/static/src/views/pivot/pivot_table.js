// @ts-check
/** @odoo-module native */

/**
 * @module pivot_table
 */

import { _t } from "@web/core/translation";

import { getLeafCounts } from "./pivot_group_tree.js";
import {
    getCellCurrency,
    getCellValue,
    getMeasuresRow,
    makeCellKey,
} from "./pivot_measurements.js";

/**
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

    /** @type {Record<string, any>[][]} */
    const colGroupRows = Array.from({ length: height }, () => []);
    colGroupRows[0].push({
        height: height + 1,
        title: "",
        width: 1,
    });

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

    const measuresRow = getMeasuresRow(measureColumns, metaData);
    headers.push(measuresRow);

    return headers;
}

/**
 * @param {Object} tree
 * @param {Object[]} columns
 * @param {Object} data
 * @param {Object} metaData
 * @returns {Object[]}
 */
export function getTableRows(tree, columns, data, metaData) {
    const rows = [];
    const columnKeys = columns.map((column) => JSON.stringify(column.groupId[1]));
    _collectTableRows(tree, columns, columnKeys, data, metaData, rows);
    return rows;
}

/**
 * @param {Object} tree
 * @param {Object[]} columns
 * @param {string[]} columnKeys
 * @param {Object} data
 * @param {Object} metaData
 * @param {Object[]} rows
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

    const subTreeKeys =
        tree.sortedKeys && tree.sortedKeys.length === tree.directSubTrees.size
            ? tree.sortedKeys
            : [...tree.directSubTrees.keys()];
    for (const subTreeKey of subTreeKeys) {
        const subTree = tree.directSubTrees.get(subTreeKey);
        _collectTableRows(subTree, columns, columnKeys, data, metaData, rows);
    }
}
