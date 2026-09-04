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
 * @property {(group: any, groupBys: string[], config: any) => any[]} [buildGroupLabels]
 * @property {(group: any, groupBys: string[]) => any[]} [buildGroupValues]
 * @property {(config: any) => string[]} [buildMeasureSpecs]
 * @property {(subGroup: any, config: any, measureSpecs: string[]) => Record<string, any>} [buildMeasurements]
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

    const measureSpecs = (deps.buildMeasureSpecs ?? getMeasureSpecs)(config);
    const buildMeasurements = deps.buildMeasurements ?? getMeasurements;
    const buildGroupValues =
        deps.buildGroupValues ??
        ((grp, groupBys) => getGroupValues(grp, groupBys, metaData.fields));
    const buildGroupLabels =
        deps.buildGroupLabels ??
        ((grp, groupBys, cfg) => getGroupLabels(grp, groupBys, cfg, metaData.fields));

    groupSubdivisions.forEach((groupSubdivision) => {
        groupSubdivision.subGroups.forEach((subGroup) => {
            const rowValues = [
                ...groupRowValues,
                ...buildGroupValues(subGroup, groupSubdivision.rowGroupBy),
            ];
            const rowLabels = [
                ...groupRowLabels,
                ...buildGroupLabels(subGroup, groupSubdivision.rowGroupBy, config),
            ];

            const colValues = [
                ...groupColValues,
                ...buildGroupValues(subGroup, groupSubdivision.colGroupBy),
            ];
            const colLabels = [
                ...groupColLabels,
                ...buildGroupLabels(subGroup, groupSubdivision.colGroupBy, config),
            ];

            if (!colValues.length && rowValues.length) {
                addGroup(data.rowGroupTree, rowLabels, rowValues);
            }
            if (colValues.length && !rowValues.length) {
                addGroup(data.colGroupTree, colLabels, colValues);
            }

            const key = JSON.stringify([rowValues, colValues]);

            data.measurements[key] = buildMeasurements(subGroup, config, measureSpecs);
            data.currencyIds[key] = getCurrencyIds(subGroup, config, measureSpecs);
            data.counts[key] = subGroup.__count;

            data.groupDomains[key] = subGroup.__domain ?? Domain.FALSE.toList();
        });
    });

    if (metaData.sortedColumn) {
        deps.sortRows(metaData.sortedColumn, config);
    }
}
