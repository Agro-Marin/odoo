// @ts-check
/** @odoo-module native */

import { onWillStart, useState } from "@odoo/owl";
import { getCurrencyRates } from "@web/core/currency";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { AGGREGATABLE_FIELD_TYPES } from "@web/model/relational_model";
import { usePopover } from "@web/ui/popover/popover_hook";
import { MultiCurrencyPopover } from "@web/views/view_components/multi_currency_popover";
import { computeAggregatedValue } from "@web/views/view_measurements";

const formatters = registry.category("formatters");

/**
 * @type {("sum" | "avg" | "max" | "min")[]}
 */
const AGGREGATE_ATTRS = ["sum", "avg", "max", "min"];

/**
 * @param {Record<string, object>} fields
 * @param {object} column
 * @returns {string}
 */
function resolveCurrencyField(fields, column) {
    return (
        column?.options?.currency_field ||
        fields[column?.name]?.currency_field ||
        "currency_id"
    );
}

/**
 * @param {object} column
 * @returns {"sum" | "avg" | "max" | "min" | undefined}
 */
function aggregateFunction(column) {
    return AGGREGATE_ATTRS.find((agg) => Boolean(column.attrs?.[agg]));
}

/**
 * @param {Record<string, any>} attrs
 * @param {any} fieldDigits
 * @param {string} [fieldName]
 * @returns {Record<string, any>}
 */
function buildFormatOptions(attrs, fieldDigits, fieldName) {
    let digits = fieldDigits;
    if (attrs.digits) {
        try {
            digits = JSON.parse(/** @type {string} */ (attrs.digits));
        } catch (error) {
            throw new Error(
                `List arch parsing error: invalid "digits" attribute on ` +
                    `<field name="${fieldName ?? attrs.name ?? "?"}"/> ` +
                    `(must be a JSON array, e.g. [16,2]): ${error.message}`,
                { cause: error },
            );
        }
    }
    return { digits, escape: true };
}

/**
 * @param {Object} column
 * @param {Record<string, any>} field
 * @returns {{ formatter: Function | false, formatOptions: Record<string, any> }}
 */
function resolveAggregateFormat(column, field) {
    const { attrs = {}, widget } = column;
    const formatter =
        formatters.get(/** @type {string} */ (widget), /** @type {any} */ (false)) ||
        formatters.get(field.type, /** @type {any} */ (false));
    return {
        formatter,
        formatOptions: buildFormatOptions(attrs, field.digits, column.name),
    };
}

/**
 * @param {any[]} columns
 * @param {Record<string, any>} fields
 * @returns {boolean}
 */
function hasMonetaryAggregate(columns, fields) {
    return columns.some((column) => {
        if (column.type !== "field") {
            return false;
        }
        const field = fields[column.name];
        if (field.type !== "monetary" && column.widget !== "monetary") {
            return false;
        }
        return Boolean(aggregateFunction(column));
    });
}

/**
 * @param {Pick<import("./list_renderer").ListGridContext, "getColumns" | "getFields" | "getProps" | "getOptionalActiveFields">} ctx
 * @returns {{
 * computeAggregates: () => Record<string, object>,
 * formatGroupAggregate: (group: object, column: object) => object,
 * getFieldCurrencies: (fieldName: string) => Set,
 * getCurrencyField: (column: object) => string,
 * openMultiCurrencyPopover: (ev: Event, value: any, fieldName: string) => void,
 * state: { currencyRates: Record<number, any> | null, ratesFailed: boolean },
 * }}
 */
export function useListAggregates(ctx) {
    const { getColumns, getFields, getProps, getOptionalActiveFields } = ctx;
    const multiCurrencyPopover = usePopover(MultiCurrencyPopover, {
        position: "right",
    });
    /** @type {{ currencyRates: Record<number, any> | null, ratesFailed: boolean }} */
    const state = useState({ currencyRates: null, ratesFailed: false });

    let ratesRequested = false;

    /**
     * @returns {Promise<void>}
     */
    async function requestCurrencyRates() {
        if (ratesRequested) {
            return;
        }
        ratesRequested = true;
        try {
            state.currencyRates = await getCurrencyRates();
        } catch (error) {
            state.ratesFailed = true;
            console.error(error);
        }
    }

    onWillStart(() => {
        if (hasMonetaryAggregate(getProps().archInfo.columns, getFields())) {
            return requestCurrencyRates();
        }
    });

    function getAggregationValues() {
        const { list } = getProps();
        if (list.selection.length) {
            return list.selection.map((r) => r.data);
        }
        if (/** @type {any} */ (list).isGrouped) {
            return /** @type {any} */ (list).groups.map((/** @type {any} */ g) => ({
                ...g.aggregates,
                __count: g.count,
            }));
        }
        return list.records.map((r) => r.data);
    }

    const self = {
        state,

        /**
         * @param {object} column
         * @returns {string}
         */
        getCurrencyField(column) {
            return resolveCurrencyField(getFields(), column);
        },

        /**
         * @param {string} fieldName
         * @returns {Set}
         */
        getFieldCurrencies(fieldName) {
            const columns = getColumns();
            const column = columns.find((c) => c.name === fieldName);
            const currencyField = self.getCurrencyField(column);
            const values = getAggregationValues();
            const { list } = getProps();
            if (/** @type {any} */ (list).isGrouped && !list.selection.length) {
                return values.reduce((set, value) => {
                    if (Array.isArray(value[currencyField])) {
                        value[currencyField].forEach((c) => set.add(c));
                    }
                    return set;
                }, new Set());
            }
            return values.reduce(
                (set, value) => set.add(value[currencyField]?.id || false),
                new Set(),
            );
        },

        /**
         * @returns {Record<string, object>}
         */
        computeAggregates() {
            const columns = getColumns();
            const fields = getFields();
            const optionalActiveFields = getOptionalActiveFields();
            const { list } = getProps();
            const aggregates = {};
            /** @type {Record<string, any>[] | null} */
            /** @type {Record<string, any>[] | null} */
            let values = null;

            for (const column of columns) {
                if (column.type !== "field") {
                    continue;
                }
                const fieldName = column.name;
                if (
                    fieldName in optionalActiveFields &&
                    !optionalActiveFields[fieldName]
                ) {
                    continue;
                }
                const field = fields[fieldName];
                const type = field.type;
                if (!AGGREGATABLE_FIELD_TYPES.includes(type)) {
                    continue;
                }
                const { attrs = {}, widget } = column;
                const func = aggregateFunction(column);
                if (!func) {
                    continue;
                }
                // The value of `??=` is the filled array, which is what the
                // reads below want; `values` itself stays the lazy cache.
                const rows = (values ??= getAggregationValues());
                const fieldEntries = [];
                for (const record of rows) {
                    const value = record[fieldName];
                    if (value || value === 0) {
                        fieldEntries.push({ value, record });
                    }
                }
                if (!fieldEntries.length) {
                    continue;
                }
                let currencyId;
                let multiCurrency = false;
                let hasMixedCurrencyGroup = false;
                let missingRates = false;
                let unknownRate = false;
                if (type === "monetary" || widget === "monetary") {
                    const currencyField = self.getCurrencyField(column);
                    if (currencyField in list.activeFields) {
                        const isGroupedAggregation =
                            /** @type {any} */ (list).isGrouped &&
                            !list.selection.length;
                        if (isGroupedAggregation) {
                            currencyId = rows.find((v) => v[currencyField]?.length)?.[
                                currencyField
                            ][0];
                        } else {
                            currencyId =
                                rows[0][currencyField] && rows[0][currencyField].id;
                        }
                        if (func && type === "monetary") {
                            const currencies = self.getFieldCurrencies(fieldName);
                            if (currencies.size > 1) {
                                multiCurrency = true;
                                currencyId = user.activeCompany?.currency_id;
                                hasMixedCurrencyGroup =
                                    isGroupedAggregation &&
                                    fieldEntries.some(
                                        (entry) =>
                                            entry.record[currencyField]?.length > 1,
                                    );
                                const rates = state.currencyRates;
                                if (!hasMixedCurrencyGroup && !rates) {
                                    requestCurrencyRates();
                                    missingRates = true;
                                } else if (!hasMixedCurrencyGroup) {
                                    const converted = [];
                                    for (const entry of fieldEntries) {
                                        const currency = isGroupedAggregation
                                            ? entry.record[currencyField]?.[0]
                                            : entry.record[currencyField]?.id;
                                        if (!currency || currency === currencyId) {
                                            converted.push(entry.value);
                                            continue;
                                        }
                                        const rate = rates?.[currency]?.toCompanyRate;
                                        if (rate === undefined) {
                                            unknownRate = true;
                                            break;
                                        }
                                        converted.push(entry.value * rate);
                                    }
                                    if (!unknownRate) {
                                        fieldEntries.forEach((entry, index) => {
                                            entry.value = converted[index];
                                        });
                                    }
                                }
                            }
                        }
                    }
                }
                if (missingRates || unknownRate) {
                    let help;
                    if (unknownRate) {
                        help = _t("No total: one currency has no exchange rate");
                    } else if (state.ratesFailed) {
                        help = _t("No total: currency rates could not be loaded");
                    } else {
                        help = _t("No total: currency rates are still loading");
                    }
                    aggregates[fieldName] = {
                        help,
                        value: "",
                        multiCurrency: true,
                        rawValue: undefined,
                    };
                    continue;
                }
                if (hasMixedCurrencyGroup) {
                    aggregates[fieldName] = {
                        help: _t("No total: a group mixes several currencies"),
                        value: "",
                        multiCurrency: true,
                        rawValue: undefined,
                    };
                    continue;
                }
                if (func) {
                    let aggregatedValue;
                    if (
                        func === "avg" &&
                        /** @type {any} */ (list).isGrouped &&
                        !list.selection.length
                    ) {
                        const aggregator = field.aggregator || "sum";
                        const totalCount = fieldEntries.reduce(
                            (s, e) => s + (e.record.__count || 0),
                            0,
                        );
                        if (totalCount && aggregator === "avg") {
                            aggregatedValue =
                                fieldEntries.reduce(
                                    (s, e) => s + e.value * (e.record.__count || 0),
                                    0,
                                ) / totalCount;
                        } else if (totalCount && aggregator === "sum") {
                            aggregatedValue =
                                fieldEntries.reduce((s, e) => s + e.value, 0) /
                                totalCount;
                        }
                    }
                    if (aggregatedValue === undefined) {
                        aggregatedValue = computeAggregatedValue(
                            fieldEntries.map((entry) => entry.value),
                            func,
                        );
                    }
                    const { formatter, formatOptions } = resolveAggregateFormat(
                        column,
                        field,
                    );
                    if (currencyId) {
                        formatOptions.currencyId = currencyId;
                    }
                    aggregates[fieldName] = {
                        help: multiCurrency ? "" : attrs[func],
                        value: formatter
                            ? formatter(aggregatedValue, formatOptions)
                            : aggregatedValue,
                        multiCurrency,
                        rawValue: aggregatedValue,
                    };
                }
            }
            return aggregates;
        },

        /**
         * @param {object} group
         * @param {object} column
         * @returns {{ value: string, multiCurrency?: boolean, rawValue?: number }}
         */
        formatGroupAggregate(group, column) {
            const { widget } = column;
            const fields = getFields();
            const field = fields[column.name];
            const aggregateValue = group.aggregates[column.name];
            if (
                !(column.name in group.aggregates) ||
                widget === "handle" ||
                !AGGREGATABLE_FIELD_TYPES.includes(field.type)
            ) {
                return { value: "" };
            }
            const { formatter, formatOptions } = resolveAggregateFormat(column, field);
            if (field.type === "monetary") {
                const currencyField = resolveCurrencyField(fields, column);
                const currencies = group.aggregates[currencyField];
                if (currencies?.length > 1 && aggregateValue !== false) {
                    formatOptions.currencyId = user.activeCompany?.currency_id;
                    return {
                        value: formatter
                            ? formatter(aggregateValue, formatOptions)
                            : aggregateValue,
                        multiCurrency: true,
                        rawValue: aggregateValue,
                    };
                }
                formatOptions.currencyId = currencies?.[0];
            }
            return {
                value: formatter
                    ? formatter(aggregateValue, formatOptions)
                    : aggregateValue,
            };
        },

        /**
         * @param {Event} ev
         * @param {any} value
         * @param {string} fieldName
         */
        openMultiCurrencyPopover(ev, value, fieldName) {
            if (value === undefined) {
                return;
            }
            if (!multiCurrencyPopover.isOpen) {
                multiCurrencyPopover.open(/** @type {HTMLElement} */ (ev.target), {
                    currencyIds: Array.from(self.getFieldCurrencies(fieldName)),
                    target: /** @type {HTMLElement} */ (ev.target),
                    value,
                });
            }
        },
    };

    return self;
}
