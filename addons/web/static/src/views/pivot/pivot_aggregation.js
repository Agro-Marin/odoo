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
 *   Renderer-supplied row sort. Called as the final step when
 *   ``metaData.sortedColumn`` is set so the row tree is re-sorted
 *   after new measurements land. Kept on the model so subclasses
 *   that override ``_sortRows`` continue to win.
 */

/**
 * Fold ``groupSubdivisions`` into the pivot's in-memory ``data`` tree.
 *
 * For each sub-group of each subdivision the function:
 *
 *   1. Concatenates the row / col values + labels with the parent
 *      ``group``'s coordinates so leaf keys are fully qualified.
 *   2. Inserts the resulting node into ``rowGroupTree`` /
 *      ``colGroupTree`` when only one axis is set (the other axis's
 *      branch is shared across sub-groups, so we never double-insert).
 *   3. Writes the (rowValues, colValues)-keyed entries into
 *      ``measurements``, ``currencyIds``, ``counts`` and
 *      ``groupDomains``. A missing ``__domain`` on the sub-group
 *      maps to ``Domain.FALSE`` so a click on the corresponding cell
 *      opens an empty list rather than producing a server-side
 *      "domain undefined" trace.
 *
 * Pure data transformation aside from ``deps.sortRows`` which is the
 * one renderer hook this stage needs (sorted-column display has to
 * re-rank after measurements land).
 *
 * The function MUTATES ``config.data`` — same contract as the
 * original ``PivotModel._prepareData`` method.
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

    // Compute the measure specs once for the whole pass rather than per
    // sub-group; getMeasureSpecs also mutates the shared field descriptors
    // (field.aggregator), so computing once reduces that churn.
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

            // Avoid double-inserting the leaf: when both axes are non-empty
            // the cell sits inside an existing row × column branch and
            // gets keyed below; only the single-axis cases need a new
            // tree node.
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
