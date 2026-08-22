// @ts-check
/** @odoo-module native */

/**
 * @typedef {Record<string, any>} ServerGroup
 */

/**
 * @typedef {Record<string, any>} FieldsMap
 */

/**
 * @typedef {{ fieldName: string, spec: string, [key: string]: any }} GroupByLevel
 */

/**
 * @typedef {Record<string, Record<string, number>>} Numbering
 */

/**
 * @typedef {{
 * count: any,
 * domain: any,
 * value: any,
 * labels: any[],
 * isFalsyXGroup: boolean,
 * identifier: string,
 * xIdentifier: string,
 * datasetId: string,
 * cumulatedStart: any,
 * convertedCumulatedStart?: any,
 * currencyId?: any,
 * convertedValue?: any,
 * }} GraphDataPoint
 */

/**
 * @typedef {{
 * currencyId?: any,
 * value?: any,
 * cumulatedStart?: any,
 * convertedValue?: any,
 * convertedCumulatedStart?: any,
 * [key: string]: any,
 * }} CurrencyResolvable
 */

/**
 * @param {string} measure
 * @param {FieldsMap} fields
 * @returns {{measures: string[], fieldAggregate: string, monetaryAggregates: string[] | undefined}}
 */
export function getMeasureSpec(measure, fields) {
    const measures = ["__count"];
    if (measure === "__count") {
        return { measures, fieldAggregate: "__count", monetaryAggregates: undefined };
    }
    const { currency_field, name, type } = fields[measure];
    let { aggregator } = fields[measure];
    if (type === "many2one") {
        aggregator = "count_distinct";
    }
    if (aggregator === undefined) {
        throw new Error(
            `No aggregate function has been provided for the measure '${measure}'`,
        );
    }
    let monetaryAggregates;
    if (type === "monetary" && currency_field) {
        monetaryAggregates = [
            `${currency_field}:array_agg_distinct`,
            `${name}:sum_currency`,
        ];
        measures.push(...monetaryAggregates);
    }
    const fieldAggregate = `${measure}:${aggregator}`;
    measures.push(fieldAggregate);
    return { measures, fieldAggregate, monetaryAggregates };
}

/**
 * @param {ServerGroup} group
 * @param {string[]} monetaryAggregates
 * @returns {any[]}
 */
export function getGroupCurrencies(group, monetaryAggregates) {
    return (group[monetaryAggregates[0]] || []).filter(
        (/** @type {any} */ currencyId) => currencyId != null,
    );
}

/**
 * @param {ServerGroup[]} startGroups
 * @param {Object} params
 * @param {GroupByLevel[]} params.groupBy
 * @param {string | null} params.sequentialField
 * @param {string} params.fieldAggregate
 * @param {string[]} [params.monetaryAggregates]
 * @param {any} [params.defaultCurrency]
 * @param {Set<any>} params.graphCurrencies
 * @returns {{cumulatedStartValue: Record<string, any>, cumulatedStartConverted: Record<string, any>}}
 */
export function foldCumulatedStart(
    startGroups,
    {
        groupBy,
        sequentialField,
        fieldAggregate,
        monetaryAggregates,
        defaultCurrency,
        graphCurrencies,
    },
) {
    /** @type {Record<string, any>} */
    const cumulatedStartValue = {};
    /** @type {Record<string, any>} */
    const cumulatedStartConverted = {};
    const keptGroupBy = groupBy.filter((gb) => gb.fieldName !== sequentialField);
    for (const group of startGroups) {
        const rawValues = keptGroupBy.map((gb) => ({ [gb.spec]: group[gb.spec] }));
        const key = JSON.stringify(rawValues);
        let value = group[fieldAggregate];
        if (monetaryAggregates) {
            const currencies = getGroupCurrencies(group, monetaryAggregates);
            cumulatedStartConverted[key] = group[monetaryAggregates[1]];
            if (currencies.length > 1) {
                value = cumulatedStartConverted[key];
                graphCurrencies.add(defaultCurrency);
            } else if (currencies.length === 1) {
                graphCurrencies.add(currencies[0]);
            }
        }
        cumulatedStartValue[key] = value;
    }
    return { cumulatedStartValue, cumulatedStartConverted };
}

/**
 * @param {any} val
 * @param {GroupByLevel} gb
 * @param {FieldsMap} fields
 * @param {Numbering} numbering
 * @param {(gb: GroupByLevel) => string} getDefaultFilterLabel
 * @returns {any}
 */
export function getValueLabel(val, gb, fields, numbering, getDefaultFilterLabel) {
    const { fieldName } = gb;
    const { type } = fields[fieldName];
    if (type === "boolean") {
        return `${val}`;
    }
    if (type === "integer") {
        return val === false ? "0" : `${val}`;
    }
    if (val === false) {
        return getDefaultFilterLabel(gb);
    }
    if (["many2many", "many2one"].includes(type)) {
        const [id, name] = val;
        const key = JSON.stringify([fieldName, name]);
        if (!numbering[key]) {
            numbering[key] = {};
        }
        const numbers = numbering[key];
        if (!numbers[id]) {
            numbers[id] = Object.keys(numbers).length + 1;
        }
        const num = numbers[id];
        return num === 1 ? name : `${name} (${num})`;
    }
    if (type === "selection") {
        const selected = fields[fieldName].selection.find(
            (/** @type {[any, string]} */ s) => s[0] === val,
        );
        return selected ? selected[1] : String(val);
    }
    if (["date", "datetime"].includes(type)) {
        return val[1];
    }
    return val;
}

/**
 * @param {ServerGroup} group
 * @param {Object} params
 * @param {GroupByLevel[]} params.groupBy
 * @param {FieldsMap} params.fields
 * @param {Numbering} params.numbering
 * @param {(gb: GroupByLevel) => string} params.getDefaultFilterLabel
 * @returns {{labels: any[], rawValues: Record<string, any>[], isFalsyXGroup: boolean}}
 */
export function getGroupLabels(
    group,
    { groupBy, fields, numbering, getDefaultFilterLabel },
) {
    const labels = [];
    /** @type {Record<string, any>[]} */
    const rawValues = [];
    let isFalsyXGroup = false;
    for (const [gbIndex, gb] of groupBy.entries()) {
        const val = group[gb.spec];
        rawValues.push({ [gb.spec]: val });
        if (val === false && gbIndex === 0) {
            const { type } = fields[gb.fieldName];
            if (type !== "boolean" && type !== "integer") {
                isFalsyXGroup = true;
            }
        }
        labels.push(getValueLabel(val, gb, fields, numbering, getDefaultFilterLabel));
    }
    return { labels, rawValues, isFalsyXGroup };
}

/**
 * @param {ServerGroup} group
 * @param {string} fieldAggregate
 * @returns {any}
 */
export function getRawValue(group, fieldAggregate) {
    return group[fieldAggregate] === false ? 0 : group[fieldAggregate];
}

/**
 * @param {ServerGroup} group
 * @param {Object} params
 * @param {any[]} params.labels
 * @param {Record<string, any>[]} params.rawValues
 * @param {boolean} params.isFalsyXGroup
 * @param {string} params.fieldAggregate
 * @param {string[]} [params.monetaryAggregates]
 * @param {any} [params.defaultCurrency]
 * @param {Set<any>} params.graphCurrencies
 * @param {Record<string, any>} params.cumulatedStartValue
 * @param {Record<string, any>} params.cumulatedStartConverted
 * @returns {GraphDataPoint}
 */
export function makeDataPoint(
    group,
    {
        labels,
        rawValues,
        isFalsyXGroup,
        fieldAggregate,
        monetaryAggregates,
        defaultCurrency,
        graphCurrencies,
        cumulatedStartValue,
        cumulatedStartConverted,
    },
) {
    const { __domain, __count } = group;
    const groupId = JSON.stringify(rawValues.slice(1));
    /** @type {GraphDataPoint} */
    const dataPoint = {
        count: __count,
        domain: __domain,
        value: getRawValue(group, fieldAggregate),
        labels,
        isFalsyXGroup,
        identifier: JSON.stringify(rawValues),
        xIdentifier: JSON.stringify(rawValues.slice(0, 1)),
        datasetId: groupId,
        cumulatedStart: cumulatedStartValue[groupId] || 0,
        convertedCumulatedStart: cumulatedStartConverted[groupId] || 0,
    };
    if (monetaryAggregates) {
        const currencies = getGroupCurrencies(group, monetaryAggregates);
        dataPoint.currencyId = currencies[0];
        dataPoint.convertedValue = group[monetaryAggregates[1]];
        if (currencies.length > 1) {
            dataPoint.currencyId = defaultCurrency;
            dataPoint.value = dataPoint.convertedValue;
        }
        if (currencies.length && __count !== 0) {
            graphCurrencies.add(dataPoint.currencyId);
        }
    }
    return dataPoint;
}

/**
 * @param {CurrencyResolvable[]} dataPoints
 * @param {Object} params
 * @param {Set<any>} params.graphCurrencies
 * @param {any} [params.defaultCurrency]
 * @param {boolean} params.hasMonetaryAggregates
 * @returns {CurrencyResolvable[]}
 */
export function applyCurrencyFallback(
    dataPoints,
    { graphCurrencies, defaultCurrency, hasMonetaryAggregates },
) {
    for (const dataPoint of dataPoints) {
        if (graphCurrencies.size > 1) {
            dataPoint.currencyId = defaultCurrency;
            if (hasMonetaryAggregates) {
                dataPoint.value = dataPoint.convertedValue;
                dataPoint.cumulatedStart = dataPoint.convertedCumulatedStart;
            }
        }
        delete dataPoint.convertedValue;
        delete dataPoint.convertedCumulatedStart;
    }
    return dataPoints;
}
