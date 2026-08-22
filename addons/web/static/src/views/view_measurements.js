// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { unique } from "@web/core/utils/collections/arrays";

/**
 * @param {Object} fields
 * @param {Object} fieldAttrs
 * @param {string[]} activeMeasures
 * @param {{ sumAggregatorOnly?: boolean }} [options]
 * @returns {Object}
 */
export const computeReportMeasures = (
    fields,
    fieldAttrs,
    activeMeasures,
    { sumAggregatorOnly = false } = {},
) => {
    const measures = {
        __count: { name: "__count", string: _t("Count"), type: "integer" },
    };
    for (const [fieldName, field] of Object.entries(fields)) {
        if (fieldName === "id") {
            continue;
        }
        const { isInvisible } = fieldAttrs[fieldName] || {};
        if (isInvisible) {
            continue;
        }
        if (
            ["integer", "float", "monetary"].includes(field.type) &&
            ((sumAggregatorOnly && field.aggregator === "sum") ||
                (!sumAggregatorOnly && field.aggregator))
        ) {
            measures[fieldName] = field;
        }
    }

    for (const measure of activeMeasures) {
        if (!measures[measure] && fields[measure]) {
            measures[measure] = fields[measure];
        }
    }

    for (const fieldName of Object.keys(fieldAttrs)) {
        if (fieldAttrs[fieldName].string && fieldName in measures) {
            measures[fieldName] = {
                ...measures[fieldName],
                string: fieldAttrs[fieldName].string,
            };
        }
    }

    const collator = new Intl.Collator(undefined, { sensitivity: "base" });
    const sortedMeasures = Object.entries(measures).sort(([m1, f1], [m2, f2]) => {
        if (m1 === "__count" || m2 === "__count") {
            return m1 === "__count" ? 1 : -1;
        }
        return collator.compare(f1.string, f2.string);
    });

    return Object.fromEntries(sortedMeasures);
};

/**
 * @param {string[]} activeMeasures
 * @param {Object} measures
 * @returns {string[]}
 */
export function dropUnknownMeasures(activeMeasures, measures) {
    const isKnown = (m) => m === "__count" || Boolean(measures[m]);
    if (activeMeasures.every(isKnown)) {
        return activeMeasures;
    }
    const kept = [];
    for (const measure of activeMeasures) {
        if (isKnown(measure)) {
            kept.push(measure);
        } else {
            console.warn(
                `Measure "${measure}" has no field definition (removed or renamed field?) and was dropped.`,
            );
        }
    }
    return kept.length ? kept : ["__count"];
}

export const CLIENT_AGGREGATORS = new Set([
    "sum",
    "avg",
    "min",
    "max",
    "count",
    "count_distinct",
]);

/**
 * @param {number[]} values
 * @param {'sum'|'avg'|'min'|'max'|'count'|'count_distinct'} aggregator
 * @throws {Error}
 */
export function computeAggregatedValue(values, aggregator) {
    if (!CLIENT_AGGREGATORS.has(aggregator)) {
        throw new Error(`Invalid aggregator '${aggregator}'`);
    }
    switch (aggregator) {
        case "count":
            return values.length;
        case "count_distinct":
            return unique(values).length;
        case "sum":
            return values.reduce((acc, v) => v + acc, 0);
        case "avg":
            return values.reduce((acc, v) => v + acc, 0) / values.length;
        case "min":
            return values.reduce((acc, v) => (v < acc ? v : acc), Infinity);
        default:
            return values.reduce((acc, v) => (v > acc ? v : acc), -Infinity);
    }
}

/**
 * @param {any | any[]} [measure]
 * @returns {any}
 */
export function processMeasure(measure) {
    if (Array.isArray(measure)) {
        return measure.map(processMeasure);
    }
    return measure === "__count__" ? "__count" : measure;
}
