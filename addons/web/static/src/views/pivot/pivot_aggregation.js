// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";

import { addGroup, findGroup } from "./pivot_group_tree.js";
import {
    getCurrencyIds,
    getMeasurements,
    getMeasureSpecs,
} from "./pivot_measurements.js";
import { getGroupLabels, getGroupValues } from "./pivot_value_utils.js";

/**
 * @typedef {Record<string, any>} PivotAggregateDeps
 * @property {(sortedColumn: any, config: any) => void} sortRows
 */

/**
 * @param {{ rowValues: any[]; colValues: any[] }} group
 * @param {Array<{ subGroups: any[]; rowGroupBy: any; colGroupBy: any }>} groupSubdivisions
 * @param {any} config
 * @param {PivotAggregateDeps} deps
 */
export function aggregateSubdivisions(group, groupSubdivisions, config, deps) {
    const { data, metaData } = config;
    const groupRowValues = group.rowValues;
    let groupRowLabels = [];
    if (groupRowValues.length) {
        const rowSubTree = findGroup(data.rowGroupTree, groupRowValues);
        if (!rowSubTree) {
            return;
        }
        groupRowLabels = rowSubTree.root.labels;
    }

    const groupColValues = group.colValues;
    let groupColLabels = [];
    if (groupColValues.length) {
        const colSubTree = findGroup(data.colGroupTree, groupColValues);
        if (!colSubTree) {
            return;
        }
        groupColLabels = colSubTree.root.labels;
    }

    const measureSpecs = getMeasureSpecs(config);

    groupSubdivisions.forEach((groupSubdivision) => {
        groupSubdivision.subGroups.forEach((subGroup) => {
            const rowValues = [
                ...groupRowValues,
                ...getGroupValues(
                    subGroup,
                    groupSubdivision.rowGroupBy,
                    metaData.fields,
                ),
            ];
            const rowLabels = [
                ...groupRowLabels,
                ...getGroupLabels(
                    subGroup,
                    groupSubdivision.rowGroupBy,
                    config,
                    metaData.fields,
                ),
            ];

            const colValues = [
                ...groupColValues,
                ...getGroupValues(
                    subGroup,
                    groupSubdivision.colGroupBy,
                    metaData.fields,
                ),
            ];
            const colLabels = [
                ...groupColLabels,
                ...getGroupLabels(
                    subGroup,
                    groupSubdivision.colGroupBy,
                    config,
                    metaData.fields,
                ),
            ];

            if (!colValues.length && rowValues.length) {
                addGroup(data.rowGroupTree, rowLabels, rowValues);
            }
            if (colValues.length && !rowValues.length) {
                addGroup(data.colGroupTree, colLabels, colValues);
            }

            const key = JSON.stringify([rowValues, colValues]);

            data.measurements[key] = getMeasurements(subGroup, config, measureSpecs);
            data.currencyIds[key] = getCurrencyIds(subGroup, config, measureSpecs);
            data.counts[key] = subGroup.__count;

            data.groupDomains[key] = subGroup.__domain ?? Domain.FALSE.toList();
        });
    });

    if (metaData.sortedColumn) {
        deps.sortRows(metaData.sortedColumn, config);
    }
}
