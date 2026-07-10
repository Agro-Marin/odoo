// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_aggregation - Walks groupSubdivisions and writes measurements/currencies/counts/domains into the in-memory pivot data tree */

import { Domain } from "@web/core/domain";

import { addGroup, findGroup } from "./pivot_group_tree.js";
import {
    getCurrencyIds,
    getMeasurements,
    getMeasureSpecs,
} from "./pivot_measurements.js";
import { getGroupLabels, getGroupValues } from "./pivot_value_utils.js";

/**
 * @typedef {object} PivotAggregateDeps
 * @property {(sortedColumn: any, config: any) => void} sortRows
 *   Renderer-supplied row sort, called after new measurements land when
 *   `metaData.sortedColumn` is set. Kept on the model so subclass overrides
 *   of `_sortRows` still apply.
 */

/**
 * Fold `groupSubdivisions` into the pivot's in-memory `data` tree: concatenates
 * row/col values+labels with the parent group's coordinates, inserts the node
 * into `rowGroupTree`/`colGroupTree` only for the single-axis case (dual-axis
 * cells share an existing branch and are never double-inserted), and writes
 * measurements/currencyIds/counts/groupDomains keyed by (rowValues, colValues).
 * A missing `__domain` maps to `Domain.FALSE` so clicking that cell opens an
 * empty list instead of erroring server-side.
 *
 * MUTATES `config.data` — same contract as the original `PivotModel._prepareData`.
 *
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
        groupRowLabels = rowSubTree.root.labels;
    }

    const groupColValues = group.colValues;
    let groupColLabels = [];
    if (groupColValues.length) {
        groupColLabels = findGroup(data.colGroupTree, groupColValues).root.labels;
    }

    // Compute measure specs once for the whole pass, not per sub-group.
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

            // Both axes non-empty: the cell sits in an existing branch and is
            // keyed below; only single-axis cases need a new tree node.
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
