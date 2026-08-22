// @ts-check
/** @odoo-module native */

/**
 * @param {Object} config
 * @returns {string[]}
 */
export function getMeasureSpecs(config) {
    const { metaData } = config;
    const seenCurrencySpecs = new Set();
    return metaData.activeMeasures.reduce((acc, measure) => {
        if (measure === "__count") {
            acc.push(measure);
            return acc;
        }
        const field = metaData.fields[measure];
        const aggregator =
            field.type === "many2one" ? "count_distinct" : field.aggregator;
        if (aggregator === undefined) {
            throw new Error(
                `No aggregate function has been provided for the measure '${measure}'`,
            );
        }
        acc.push(`${measure}:${aggregator}`);
        if (field.currency_field) {
            const currencySpec = `${field.currency_field}:array_agg_distinct`;
            if (!seenCurrencySpecs.has(currencySpec)) {
                seenCurrencySpecs.add(currencySpec);
                acc.push(currencySpec);
            }
            if (aggregator === "sum") {
                acc.push(`${field.name}:sum_currency`);
            }
        }
        return acc;
    }, []);
}

/**
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
            currencyIds[fieldName] = (
                group[`${measureField.currency_field}:array_agg_distinct`] || []
            ).filter((currencyId) => currencyId != null);
        }
        return currencyIds;
    }, {});
}

/**
 * @param {string} rowKey
 * @param {string} colKey
 * @returns {string}
 */
export function makeCellKey(rowKey, colKey) {
    return `[${rowKey},${colKey}]`;
}

/**
 * @param {string} cellKey
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
 * @param {string} cellKey
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
