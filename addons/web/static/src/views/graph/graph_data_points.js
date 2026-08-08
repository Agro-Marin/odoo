// @ts-check
/** @odoo-module native */

/** @module @web/views/graph/graph_data_points */

/**
 * The data-shaping half of `graph_model`, as pure functions.
 *
 * `GraphModel._loadDataPoints` was 195 lines — the unit's longest — and every
 * branch in it (eight label shapes, the monetary multi-currency fallback, the
 * cumulated-start fold) was reachable only through a mounted webclient, because
 * the shaping sat between two `orm.formattedReadGroup` awaits. `views/pivot` does
 * not have that problem: its logic lives in `pivot_group_tree`, `pivot_measurements`
 * and `pivot_value_utils`, so `pivot_model.test.js` tests functions rather than a
 * class. This module is that same move for graph.
 *
 * Everything here takes what it needs as an argument — `defaultCurrency` rather
 * than `user.activeCompany`, a `getDefaultFilterLabel` callback rather than
 * `this.metaData` — so the ORM stays in the model and the shaping is callable
 * from a test with a literal.
 */

/**
 * One row of a `formattedReadGroup` response. Keyed by measure spec
 * (`"amount:sum"`), by groupBy spec (`"date:month"`), and by the `__`-prefixed
 * bookkeeping the server adds, so it is a record by nature rather than a shape.
 *
 * @typedef {Record<string, any>} ServerGroup
 */

/**
 * `fields_get`-shaped descriptors, keyed by field name. This module reads
 * `type`, `aggregator`, `currency_field`, `name` and `selection` off them.
 *
 * @typedef {Record<string, any>} FieldsMap
 */

/**
 * One groupBy level. `fieldName` is the field; `spec` is the key the server
 * answers under, which differs for a granularity (`date` vs `date:month`) —
 * reading the wrong one of the two is the mistake this typedef exists to make
 * visible.
 *
 * @typedef {{ fieldName: string, spec: string, [key: string]: any }} GroupByLevel
 */

/**
 * The display-name disambiguation accumulator: `[fieldName, name]` to a map of
 * record id to its 1-based occurrence. Mutated across every group of a load, so
 * two records sharing a display name read `name`, `name (2)`, … in first-seen
 * order.
 *
 * @typedef {Record<string, Record<string, number>>} Numbering
 */

/**
 * One assembled point.
 *
 * `currencyId`, `convertedValue` and `convertedCumulatedStart` are optional
 * because only a monetary measure has them, and the last two are scratch space
 * `applyCurrencyFallback` deletes on the way out.
 *
 * @typedef {{
 *   count: any,
 *   domain: any,
 *   value: any,
 *   labels: any[],
 *   isFalsyXGroup: boolean,
 *   identifier: string,
 *   xIdentifier: string,
 *   datasetId: string,
 *   cumulatedStart: any,
 *   convertedCumulatedStart?: any,
 *   currencyId?: any,
 *   convertedValue?: any,
 * }} GraphDataPoint
 */

/**
 * What `applyCurrencyFallback` actually requires: the five keys it reads or
 * writes, all optional. Narrower than `GraphDataPoint` on purpose — the pass is
 * a mutation over monetary scratch space, not something that needs a whole
 * point, and saying so lets a test hand it the two fields a case is about
 * instead of a fully-populated literal that obscures which ones matter.
 *
 * @typedef {{
 *   currencyId?: any,
 *   value?: any,
 *   cumulatedStart?: any,
 *   convertedValue?: any,
 *   convertedCumulatedStart?: any,
 *   [key: string]: any,
 * }} CurrencyResolvable
 */

/**
 * Build the `formattedReadGroup` measure specs for a graph measure.
 *
 * Mirrors `pivot_measurements.getMeasureSpecs`, including the `many2one` override
 * and the missing-aggregator throw; graph differs in returning the single
 * `fieldAggregate` it later reads values by, and in that `__count` is always the
 * first spec.
 *
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
 * The currency ids a monetary group spans, with the nulls dropped.
 *
 * `array_agg_distinct` yields `null` for rows whose currency is unset, and a
 * group that is entirely unset yields `false` rather than an array — both would
 * otherwise be counted as a currency and trip the multi-currency fallback.
 *
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
 * Fold the pre-window groups into the cumulated-start offsets the main pass adds.
 *
 * Keyed by the groupBy values *excluding* the sequential (date) field, which is
 * what makes the key comparable to the main pass's `rawValues.slice(1)`.
 *
 * @param {ServerGroup[]} startGroups
 * @param {Object} params
 * @param {GroupByLevel[]} params.groupBy
 * @param {string | null} params.sequentialField
 * @param {string} params.fieldAggregate
 * @param {string[]} [params.monetaryAggregates]
 * @param {any} [params.defaultCurrency]
 * @param {Set<any>} params.graphCurrencies accumulated across both passes
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
 * The display label for one groupBy value.
 *
 * Branch order is load-bearing: `boolean` and `integer` are answered before the
 * generic `val === false` case, so a false boolean reads "false" and a false
 * integer reads "0" rather than both collapsing into the falsy-value label.
 *
 * `numbering` is a mutable accumulator shared across every group of a load: two
 * distinct records with the same display name are disambiguated as `name`,
 * `name (2)`, … in first-seen order, so it must not be reset per group.
 *
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
 * Labels and raw values for one group, across every groupBy level.
 *
 * `isFalsyXGroup` marks a group whose *first* (x-axis) level is falsy; line and
 * scatter modes drop those, because a gap in the x series is not a point.
 *
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
 * The measure value of a group, with the server's empty-group `false` read as 0.
 *
 * Read separately from `makeDataPoint` because the caller needs it *before* any
 * currency conversion: `metaData.allIntegers` describes the raw aggregate, and
 * a monetary point whose value is later swapped for its converted counterpart
 * must not retroactively change that answer.
 *
 * @param {ServerGroup} group
 * @param {string} fieldAggregate
 * @returns {any}
 */
export function getRawValue(group, fieldAggregate) {
    return group[fieldAggregate] === false ? 0 : group[fieldAggregate];
}

/**
 * Assemble one data point from a server group.
 *
 * `datasetId` deliberately drops the first groupBy level: the x axis identifies
 * a point *within* a dataset, so two points sharing every level but the first
 * belong to the same series — which is also what makes the id comparable to
 * `foldCumulatedStart`'s keys.
 *
 * For a monetary measure the point carries its own currency, falling back to the
 * company currency as soon as the single group spans more than one. Empty groups
 * (`__count === 0`) do not contribute a currency, so a graph is not forced into
 * multi-currency mode by a group that has nothing in it.
 *
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
 * Resolve a graph that spans more than one currency onto the company currency.
 *
 * Mixed currencies cannot share an axis, so every point falls back to the
 * company currency and reads its server-side converted value. The converted
 * fields are scratch space and are deleted either way, so a caller cannot come
 * to depend on them.
 *
 * @param {CurrencyResolvable[]} dataPoints
 * @param {Object} params
 * @param {Set<any>} params.graphCurrencies
 * @param {any} [params.defaultCurrency]
 * @param {boolean} params.hasMonetaryAggregates
 * @returns {CurrencyResolvable[]} the same array, mutated
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
