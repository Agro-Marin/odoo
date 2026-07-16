// @ts-check
/** @odoo-module native */

/** @module @web/views/pivot/pivot_measurements - Builds measure specs (fieldName:aggregator) and data comparison logic for the pivot model */

/**
 * Returns the list of measure specs associated with active measures.
 * A measure 'fieldName' becomes 'fieldName:aggregator'.
 *
 * @param {Object} config
 * @returns {string[]}
 */
export function getMeasureSpecs(config) {
    const { metaData } = config;
    // Track the currency array_agg_distinct specs already requested: several
    // monetary measures can share one currency_field, so the same spec would
    // otherwise be pushed once per measure (L6).
    const seenCurrencySpecs = new Set();
    return metaData.activeMeasures.reduce((acc, measure) => {
        if (measure === "__count") {
            acc.push(measure);
            return acc;
        }
        const field = metaData.fields[measure];
        // compute the m2o aggregator locally: writing it back onto `field`
        // would mutate the shared field definition
        const aggregator =
            field.type === "many2one" ? "count_distinct" : field.aggregator;
        if (aggregator === undefined) {
            throw new Error(
                `No aggregate function has been provided for the measure '${measure}'`,
            );
        }
        acc.push(`${measure}:${aggregator}`);
        if (field.currency_field) {
            // array_agg_distinct is kept for every monetary measure: it drives
            // currency-symbol formatting and the multi-currency "?" popover
            // (pivot_renderer) regardless of aggregator. Deduped via the Set (L6).
            const currencySpec = `${field.currency_field}:array_agg_distinct`;
            if (!seenCurrencySpecs.has(currencySpec)) {
                seenCurrencySpecs.add(currencySpec);
                acc.push(currencySpec);
            }
            // sum_currency (convert-then-resum) is only meaningful for a summed
            // measure. Emitting it for avg/min/max let getMeasurements
            // substitute the converted SUM into those cells whenever a cell
            // spanned >1 currency (M1); gate it on the sum aggregator.
            if (aggregator === "sum") {
                acc.push(`${field.name}:sum_currency`);
            }
        }
        return acc;
    }, []);
}

/**
 * Returns the group sanitized measure values for the active measures.
 *
 * @param {Object} group
 * @param {Object} config
 * @param {string[]} measureSpecs
 * @returns {Object}
 */
export function getMeasurements(group, config, measureSpecs) {
    const { metaData } = config;
    return measureSpecs.reduce((measurements, measureName) => {
        let measurement = group[measureName];
        const [fieldName, aggregator] = measureName.split(":");
        if (aggregator === "array_agg_distinct") {
            return measurements;
        }
        if (aggregator === "sum_currency") {
            // Filter NULLs kept by array_agg_distinct (a record with an unset
            // currency): a lone NULL must not be counted as a "second currency"
            // and trigger the converted-sum substitution / "?" popover (M1).
            const currencies = (
                group[
                    `${metaData.fields[fieldName].currency_field}:array_agg_distinct`
                ] || []
            ).filter((currencyId) => currencyId != null);
            if (currencies.length <= 1) {
                return measurements;
            }
        }
        if (
            metaData.measures[fieldName].type === "boolean" &&
            typeof measurement === "boolean"
        ) {
            measurement = measurement ? 1 : 0;
        }
        measurements[fieldName] = measurement;
        return measurements;
    }, {});
}

/**
 * Returns the group sanitized currency id values for monetary measures.
 *
 * @param {Object} group
 * @param {Object} config
 * @param {string[]} measureSpecs
 * @returns {Object}
 */
export function getCurrencyIds(group, config, measureSpecs) {
    const { metaData } = config;
    return measureSpecs.reduce((currencyIds, measureName) => {
        const [fieldName, aggregator] = measureName.split(":");
        if (aggregator === "array_agg_distinct") {
            return currencyIds;
        }
        const measureField = metaData.measures[fieldName];
        if (measureField.type === "monetary" && measureField.currency_field) {
            // Filter NULLs so an unset-currency record does not fabricate a
            // "second currency" (which would flip the cell to the multi-currency
            // "?" popover in pivot_renderer) (M1).
            currencyIds[fieldName] = (
                group[`${measureField.currency_field}:array_agg_distinct`] || []
            ).filter((currencyId) => currencyId != null);
        }
        return currencyIds;
    }, {});
}

/**
 * Key under which a cell's values are stored in ``data.measurements`` /
 * ``data.currencyIds``. Equivalent to ``JSON.stringify([rowValues,
 * colValues])`` but callers pass pre-stringified parts to avoid
 * re-serializing per cell.
 *
 * @param {string} rowKey ``JSON.stringify(rowValues)``
 * @param {string} colKey ``JSON.stringify(colValues)``
 * @returns {string}
 */
export function makeCellKey(rowKey, colKey) {
    return `[${rowKey},${colKey}]`;
}

/**
 * @param {string} cellKey see ``makeCellKey``
 * @param {string} measure
 * @param {Object} data
 * @returns {number|undefined}
 */
export function getCellValue(cellKey, measure, data) {
    if (!data.measurements[cellKey]) {
        return;
    }
    return data.measurements[cellKey][measure];
}

/**
 * @param {string} cellKey see ``makeCellKey``
 * @param {string} measure
 * @param {Object} data
 * @returns {number|undefined}
 */
export function getCellCurrency(cellKey, measure, data) {
    if (!data.currencyIds[cellKey]) {
        return;
    }
    return data.currencyIds[cellKey][measure];
}

/**
 * Returns a description of the measures row of the pivot table.
 *
 * @param {Object[]} columns
 * @param {Object} metaData
 * @returns {Object[]}
 */
export function getMeasuresRow(columns, metaData) {
    const sortedColumn = metaData.sortedColumn || {};
    const sortedColumnKey = sortedColumn.groupId
        ? JSON.stringify(sortedColumn.groupId)
        : undefined;
    const measureRow = [];

    for (const column of columns) {
        const isSortedColumn =
            sortedColumnKey !== undefined &&
            sortedColumnKey === JSON.stringify(column.groupId);
        for (const measureName of metaData.activeMeasures) {
            const measureCell = {
                groupId: column.groupId,
                height: 1,
                measure: measureName,
                title: metaData.measures[measureName].string,
                width: 1,
            };
            if (isSortedColumn && sortedColumn.measure === measureName) {
                measureCell.order = sortedColumn.order;
            }
            measureRow.push(measureCell);
        }
    }

    return measureRow;
}
