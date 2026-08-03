// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_aggregates */

import { onWillStart, useState } from "@odoo/owl";
import { getCurrencyRates } from "@web/core/currency";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { AGGREGATABLE_FIELD_TYPES } from "@web/model/relational_model/utils";
import { usePopover } from "@web/ui/popover/popover_hook";
import { MultiCurrencyPopover } from "@web/views/view_components/multi_currency_popover";
import { computeAggregatedValue } from "@web/views/view_measurements";

const formatters = registry.category("formatters");

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
 * @param {Pick<import("./list_renderer").ListGridContext, "getColumns" | "getFields" | "getProps" | "getOptionalActiveFields">} ctx
 *   the subset of the grid context this hook reads; the ListRenderer passes its
 *   full `gridContext`, `ListAggregatesRow` a compatible partial.
 * @returns {{
 *   computeAggregates: () => Record<string, object>,
 *   formatGroupAggregate: (group: object, column: object) => object,
 *   getFieldCurrencies: (fieldName: string) => Set,
 *   getCurrencyField: (column: object) => string,
 *   openMultiCurrencyPopover: (ev: Event, value: any, fieldName: string) => void,
 *   state: { currencyRates: object | null },
 * }}
 */
export function useListAggregates(ctx) {
    const { getColumns, getFields, getProps, getOptionalActiveFields } = ctx;
    const multiCurrencyPopover = usePopover(MultiCurrencyPopover, {
        position: "right",
    });
    const state = useState({ currencyRates: null });

    onWillStart(async () => {
        const props = getProps();
        const fields = getFields();
        const needsCurrencyRates = /** @type {any} */ (props).archInfo.columns.some(
            (/** @type {any} */ column) => {
                if (column.type !== "field") {
                    return false;
                }
                const field = fields[column.name];
                if (field.type !== "monetary" && column.widget !== "monetary") {
                    return false;
                }
                return ["sum", "avg", "max", "min"].some((agg) => agg in column.attrs);
            },
        );
        if (needsCurrencyRates) {
            state.currencyRates = await getCurrencyRates();
        }
    });

    let ratesRequested = false;
    /** Self-heals the aggregate once the rates land. */
    function requestCurrencyRates() {
        if (ratesRequested) {
            return;
        }
        ratesRequested = true;
        getCurrencyRates()
            .then((rates) => (state.currencyRates = rates))
            .catch((error) => console.error(error));
    }

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
            const values = getAggregationValues();
            const columns = getColumns();
            const fields = getFields();
            const optionalActiveFields = getOptionalActiveFields();
            const { list } = getProps();
            const aggregates = {};

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
                const fieldEntries = [];
                for (const record of values) {
                    const value = record[fieldName];
                    if (value || value === 0) {
                        fieldEntries.push({ value, record });
                    }
                }
                if (!fieldEntries.length) {
                    continue;
                }
                const type = field.type;
                if (!AGGREGATABLE_FIELD_TYPES.includes(type)) {
                    continue;
                }
                const { attrs, widget } = column;
                const func =
                    (attrs.sum && "sum") ||
                    (attrs.avg && "avg") ||
                    (attrs.max && "max") ||
                    (attrs.min && "min");
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
                            currencyId = values.find((v) => v[currencyField]?.length)?.[
                                currencyField
                            ][0];
                        } else {
                            currencyId =
                                values[0][currencyField] && values[0][currencyField].id;
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
                                if (!hasMixedCurrencyGroup && !state.currencyRates) {
                                    // converting at an assumed rate of 1 would
                                    // print a plausible, wrong total
                                    requestCurrencyRates();
                                    missingRates = true;
                                } else if (!hasMixedCurrencyGroup) {
                                    // A currency the rate table does not cover
                                    // is the same hazard as no table at all —
                                    // the session only carries rates for the
                                    // currencies it knows, and a record may
                                    // reference one it does not. Convert into a
                                    // scratch list so a rate missing halfway
                                    // through cannot leave the entries half
                                    // converted.
                                    const converted = [];
                                    for (const entry of fieldEntries) {
                                        const currency = isGroupedAggregation
                                            ? entry.record[currencyField]?.[0]
                                            : entry.record[currencyField]?.id;
                                        // An amount with no currency at all has
                                        // no unit to convert from; it counts as
                                        // it stands, and the popover discloses
                                        // it as "without currency".
                                        if (!currency || currency === currencyId) {
                                            converted.push(entry.value);
                                            continue;
                                        }
                                        const rate =
                                            state.currencyRates[currency]
                                                ?.toCompanyRate;
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
                    aggregates[fieldName] = {
                        help: unknownRate
                            ? _t("No total: one currency has no exchange rate")
                            : _t("No total: currency rates are still loading"),
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
                    const formatter =
                        formatters.get(
                            /** @type {string} */ (widget),
                            /** @type {any} */ (false),
                        ) || formatters.get(type, /** @type {any} */ (false));
                    const formatOptions = {
                        digits: attrs.digits
                            ? JSON.parse(/** @type {string} */ (attrs.digits))
                            : undefined,
                        escape: true,
                    };
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
            const { widget, attrs } = column;
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
            const formatter =
                formatters.get(
                    /** @type {string} */ (widget),
                    /** @type {any} */ (false),
                ) || formatters.get(field.type, /** @type {any} */ (false));
            const formatOptions = {
                digits: attrs.digits
                    ? JSON.parse(/** @type {string} */ (attrs.digits))
                    : field.digits,
                escape: true,
            };
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
