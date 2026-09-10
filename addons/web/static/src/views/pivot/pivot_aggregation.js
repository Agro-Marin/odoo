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
 * @typedef PivotAggregateDeps
 * @property {(sortedColumn: any, config: any) => void} sortRows
 * @property {(group: any, groupBys: string[], config: any) => any[]} [prepareGroupLabels]
 * @property {(group: any, groupBys: string[]) => any[]} [prepareGroupValues]
 * @property {(config: any) => string[]} [prepareMeasureSpecs]
 * @property {(subGroup: any, config: any, measureSpecs: string[]) => Record<string, any>} [prepareMeasurements]
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

    const measureSpecs = (deps.prepareMeasureSpecs ?? getMeasureSpecs)(config);
    const prepareMeasurements = deps.prepareMeasurements ?? getMeasurements;
    const prepareGroupValues =
        deps.prepareGroupValues ??
        ((/** @type {Object} */ grp, /** @type {string[]} */ groupBys) =>
            getGroupValues(grp, groupBys, metaData.fields));
    const prepareGroupLabels =
        deps.prepareGroupLabels ??
        ((
            /** @type {Object} */ grp,
            /** @type {string[]} */ groupBys,
            /** @type {Object} */ cfg,
        ) => getGroupLabels(grp, groupBys, cfg, metaData.fields));

    groupSubdivisions.forEach((groupSubdivision) => {
        groupSubdivision.subGroups.forEach((subGroup) => {
            const rowValues = [
                ...groupRowValues,
                ...prepareGroupValues(subGroup, groupSubdivision.rowGroupBy),
            ];
            const rowLabels = [
                ...groupRowLabels,
                ...prepareGroupLabels(subGroup, groupSubdivision.rowGroupBy, config),
            ];

            const colValues = [
                ...groupColValues,
                ...prepareGroupValues(subGroup, groupSubdivision.colGroupBy),
            ];
            const colLabels = [
                ...groupColLabels,
                ...prepareGroupLabels(subGroup, groupSubdivision.colGroupBy, config),
            ];

            if (!colValues.length && rowValues.length) {
                addGroup(data.rowGroupTree, rowLabels, rowValues);
            }
            if (colValues.length && !rowValues.length) {
                addGroup(data.colGroupTree, colLabels, colValues);
            }

            const key = JSON.stringify([rowValues, colValues]);

            data.measurements[key] = prepareMeasurements(
                subGroup,
                config,
                measureSpecs,
            );
            data.currencyIds[key] = getCurrencyIds(subGroup, config, measureSpecs);
            data.counts[key] = subGroup.__count;

            data.groupDomains[key] = subGroup.__domain ?? Domain.FALSE.toList();
        });
    });

    if (metaData.sortedColumn) {
        deps.sortRows(metaData.sortedColumn, config);
    }
}
