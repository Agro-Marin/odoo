// @ts-check
/** @odoo-module native */

/** @module @web/views/view_measurements - Computes available report measures from field definitions and active selections */

/**
 *
 * @param {Object} fields
 * @param {Object} fieldAttrs
 * @param {string[]} activeMeasures
 * @returns {Object}
 */

import { _t } from "@web/core/l10n/translation";
import { unique } from "@web/core/utils/collections/arrays";
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

    // Include active measures not already listed: rarely needed, but supports
    // a non-stored functional field with an overridden read_group. Such
    // fields' aggregate will otherwise always be 0.
    for (const measure of activeMeasures) {
        if (!measures[measure]) {
            measures[measure] = fields[measure];
        }
    }

    for (const fieldName of Object.keys(fieldAttrs)) {
        if (fieldAttrs[fieldName].string && fieldName in measures) {
            // copy before mutating: `measures[fieldName]` aliases the live
            // shared field definition
            measures[fieldName] = {
                ...measures[fieldName],
                string: fieldAttrs[fieldName].string,
            };
        }
    }

    const sortedMeasures = Object.entries(measures).sort(([m1, f1], [m2, f2]) => {
        if (m1 === "__count" || m2 === "__count") {
            return m1 === "__count" ? 1 : -1; // Count is always last
        }
        return f1.string.toLowerCase().localeCompare(f2.string.toLowerCase());
    });

    return Object.fromEntries(sortedMeasures);
};

/**
 * Given an array of values and an aggregator function, returns the aggregated
 * value.
 *
 * @param {number[]} values
 * @param {'sum'|'avg'|'min'|'max'|'count'|'count_distinct'} aggregator
 * @returns number
 * @throws {Error} if the aggregator function given isn't supported
 */
export function computeAggregatedValue(values, aggregator) {
    if (aggregator === "sum") {
        return values.reduce((acc, v) => v + acc, 0);
    } else if (aggregator === "avg") {
        return values.reduce((acc, v) => v + acc, 0) / values.length;
    } else if (aggregator === "min") {
        // reduce instead of Math.min(...values): spreading very large arrays
        // exceeds the argument limit and throws a RangeError
        return values.reduce((acc, v) => (v < acc ? v : acc), Infinity);
    } else if (aggregator === "max") {
        return values.reduce((acc, v) => (v > acc ? v : acc), -Infinity);
    } else if (aggregator === "count") {
        return values.length;
    } else if (aggregator === "count_distinct") {
        return unique(values).length;
    }
    throw new Error(`Invalid aggregator '${aggregator}'`);
}

/**
 * Normalize legacy '__count__' (old preview-implementation name) to
 * '__count' so favorites saved before the rename still work.
 *
 * @param {any | any[]} [measure]
 * @returns {any}
 */
export function processMeasure(measure) {
    if (Array.isArray(measure)) {
        return measure.map(processMeasure);
    }
    return measure === "__count__" ? "__count" : measure;
}
