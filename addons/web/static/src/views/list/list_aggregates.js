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
 * @param {Record<string, any>[]} rows
 * @param {string} fieldName
 * @returns {{ value: any, record: Record<string, any> }[]}
 */
function collectFieldEntries(rows, fieldName) {
    const entries = [];
    for (const record of rows) {
        const value = record[fieldName];
        if (value || value === 0) {
            entries.push({ value, record });
        }
    }
    return entries;
}

/**
 * The column's field, if this column can be aggregated at all.
 *
 * @param {any} column
 * @param {Record<string, any>} fields
 * @param {Record<string, boolean>} optionalActiveFields
 * @returns {Record<string, any> | null}
 */
function aggregatableField(column, fields, optionalActiveFields) {
    if (column.type !== "field") {
        return null;
    }
    if (column.name in optionalActiveFields && !optionalActiveFields[column.name]) {
        return null;
    }
    const field = fields[column.name];
    if (!field || !AGGREGATABLE_FIELD_TYPES.includes(field.type)) {
        return null;
    }
    return field;
}

/**
 * An `avg` over groups is not the average of the group averages.
 *
 * Each row here is a group, so the mean has to be re-weighted by the number of
 * records behind it: by `__count` when the server already averaged
 * (`aggregator === "avg"`), and by dividing the summed total when it summed.
 *
 * @param {{ value: any, record: Record<string, any> }[]} fieldEntries
 * @param {string} aggregator
 * @returns {number | undefined} undefined when the caller should fall back
 */
export function weightedGroupAverage(fieldEntries, aggregator) {
    const totalCount = fieldEntries.reduce((s, e) => s + (e.record.__count || 0), 0);
    if (!totalCount) {
        return undefined;
    }
    if (aggregator === "avg") {
        return (
            fieldEntries.reduce((s, e) => s + e.value * (e.record.__count || 0), 0) /
            totalCount
        );
    }
    if (aggregator === "sum") {
        return fieldEntries.reduce((s, e) => s + e.value, 0) / totalCount;
    }
    return undefined;
}

/**
 * A cell that shows why there is no total, rather than a wrong one.
 *
 * @param {string} help
 * @returns {Record<string, any>}
 */
function blockedAggregate(help) {
    return { help, value: "", multiCurrency: true, rawValue: undefined };
}

/**
 * Rewrite each entry into `currencyId`, in place, unless a rate is missing.
 *
 * @param {{ value: any, record: Record<string, any> }[]} fieldEntries
 * @param {Object} params
 * @param {string} params.currencyField
 * @param {any} params.currencyId
 * @param {Record<number, any>} params.rates
 * @param {boolean} params.isGroupedAggregation
 * @returns {boolean} whether every entry could be converted
 */
function convertEntriesToCompanyCurrency(
    fieldEntries,
    { currencyField, currencyId, rates, isGroupedAggregation },
) {
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
            return false;
        }
        converted.push(entry.value * rate);
    }
    fieldEntries.forEach((entry, index) => {
        entry.value = converted[index];
    });
    return true;
}

/**
 * @typedef {Pick<import("./list_renderer").ListGridContext, "getColumns" | "getFields" | "getProps" | "getOptionalActiveFields">} ListAggregatesContext
 */

export class ListAggregates {
    /**
     * @param {ListAggregatesContext} ctx
     * @param {{ state: { currencyRates: Record<number, any> | null, ratesFailed: boolean }, multiCurrencyPopover: any }} deps
     */
    constructor(ctx, { state, multiCurrencyPopover }) {
        this.ctx = ctx;
        this.state = state;
        this.multiCurrencyPopover = multiCurrencyPopover;
        this.ratesRequested = false;
    }

    /**
     * @returns {Promise<void>}
     */
    async requestCurrencyRates() {
        if (this.ratesRequested) {
            return;
        }
        this.ratesRequested = true;
        try {
            this.state.currencyRates = await getCurrencyRates();
        } catch (error) {
            this.state.ratesFailed = true;
            console.error(error);
        }
    }

    /** @returns {boolean} */
    get hasMonetaryAggregate() {
        return hasMonetaryAggregate(
            this.ctx.getProps().archInfo.columns,
            this.ctx.getFields(),
        );
    }

    /** @returns {Record<string, any>[]} */
    getAggregationValues() {
        const { list } = this.ctx.getProps();
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

    /**
     * @param {object} column
     * @returns {string}
     */
    getCurrencyField(column) {
        return resolveCurrencyField(this.ctx.getFields(), column);
    }

    /**
     * @param {string} fieldName
     * @param {{ column?: object, rows?: Record<string, any>[] }} [known]
     *        what the caller already holds; computeAggregates has both, and
     *        re-deriving them per monetary column re-walked every record.
     * @returns {Set}
     */
    getFieldCurrencies(fieldName, known = {}) {
        const column =
            known.column ?? this.ctx.getColumns().find((c) => c.name === fieldName);
        const currencyField = this.getCurrencyField(column);
        const values = known.rows ?? this.getAggregationValues();
        const { list } = this.ctx.getProps();
        if (/** @type {any} */ (list).isGrouped && !list.selection.length) {
            return values.reduce((set, value) => {
                if (Array.isArray(value[currencyField])) {
                    value[currencyField].forEach((c) => set.add(c));
                }
                return set;
            }, /** @type {Set<any>} */ (new Set()));
        }
        return values.reduce(
            (set, value) => set.add(value[currencyField]?.id || false),
            /** @type {Set<any>} */ (new Set()),
        );
    }

    /**
     * The currency a monetary column totals in, and whether it can total
     * at all.
     *
     * Converting entries into the company currency is part of resolving it:
     * a total is only meaningful once every entry is in one currency, and
     * the reasons it can fail -- a group mixing currencies, rates still in
     * flight, a currency with no rate -- are the reasons there is no total.
     * `blocked` carries the one to show instead.
     *
     * @param {any} column
     * @param {Record<string, any>} field
     * @param {{ value: any, record: Record<string, any> }[]} fieldEntries
     * @param {Record<string, any>[]} rows
     * @param {boolean} isGroupedAggregation
     * @returns {{ currencyId: any, multiCurrency: boolean, blocked: string | null }}
     */
    resolveAggregateCurrency(column, field, fieldEntries, rows, isGroupedAggregation) {
        const plain = { currencyId: undefined, multiCurrency: false, blocked: null };
        if (field.type !== "monetary" && column.widget !== "monetary") {
            return plain;
        }
        const { list } = this.ctx.getProps();
        const currencyField = this.getCurrencyField(column);
        if (!(currencyField in list.activeFields)) {
            return plain;
        }
        const currencyId = isGroupedAggregation
            ? rows.find((v) => v[currencyField]?.length)?.[currencyField][0]
            : rows[0][currencyField] && rows[0][currencyField].id;
        if (field.type !== "monetary") {
            return { currencyId, multiCurrency: false, blocked: null };
        }
        const currencies = this.getFieldCurrencies(column.name, { column, rows });
        if (currencies.size <= 1) {
            return { currencyId, multiCurrency: false, blocked: null };
        }
        const companyCurrencyId = user.activeCompany?.currency_id;
        const mixed =
            isGroupedAggregation &&
            fieldEntries.some((entry) => entry.record[currencyField]?.length > 1);
        if (mixed) {
            return {
                currencyId: companyCurrencyId,
                multiCurrency: true,
                blocked: _t("No total: a group mixes several currencies"),
            };
        }
        const rates = this.state.currencyRates;
        if (!rates) {
            this.requestCurrencyRates();
            return {
                currencyId: companyCurrencyId,
                multiCurrency: true,
                blocked: this.state.ratesFailed
                    ? _t("No total: currency rates could not be loaded")
                    : _t("No total: currency rates are still loading"),
            };
        }
        const converted = convertEntriesToCompanyCurrency(fieldEntries, {
            currencyField,
            currencyId: companyCurrencyId,
            rates,
            isGroupedAggregation,
        });
        return {
            currencyId: companyCurrencyId,
            multiCurrency: true,
            blocked: converted
                ? null
                : _t("No total: one currency has no exchange rate"),
        };
    }

    /**
     * @returns {Record<string, object>}
     */
    computeAggregates() {
        const columns = this.ctx.getColumns();
        const fields = this.ctx.getFields();
        const optionalActiveFields = this.ctx.getOptionalActiveFields();
        const { list } = this.ctx.getProps();
        const isGroupedAggregation =
            Boolean(/** @type {any} */ (list).isGrouped) && !list.selection.length;
        /** @type {Record<string, any>} */
        const aggregates = {};
        /** @type {Record<string, any>[] | null} */
        let values = null;

        for (const column of columns) {
            const field = aggregatableField(column, fields, optionalActiveFields);
            if (!field) {
                continue;
            }
            const func = aggregateFunction(column);
            if (!func) {
                continue;
            }
            const rows = (values ??= this.getAggregationValues());
            const fieldEntries = collectFieldEntries(rows, column.name);
            if (!fieldEntries.length) {
                continue;
            }
            const currency = this.resolveAggregateCurrency(
                column,
                field,
                fieldEntries,
                rows,
                isGroupedAggregation,
            );
            if (currency.blocked) {
                aggregates[column.name] = blockedAggregate(currency.blocked);
                continue;
            }
            let aggregatedValue;
            if (func === "avg" && isGroupedAggregation) {
                aggregatedValue = weightedGroupAverage(
                    fieldEntries,
                    field.aggregator || "sum",
                );
            }
            aggregatedValue ??= computeAggregatedValue(
                fieldEntries.map((entry) => entry.value),
                func,
            );
            const { formatter, formatOptions } = resolveAggregateFormat(column, field);
            if (currency.currencyId) {
                formatOptions.currencyId = currency.currencyId;
            }
            aggregates[column.name] = {
                help: currency.multiCurrency ? "" : (column.attrs || {})[func],
                value: formatter
                    ? formatter(aggregatedValue, formatOptions)
                    : aggregatedValue,
                multiCurrency: currency.multiCurrency,
                rawValue: aggregatedValue,
            };
        }
        return aggregates;
    }

    /**
     * @param {object} group
     * @param {object} column
     * @returns {{ value: string, multiCurrency?: boolean, rawValue?: number }}
     */
    formatGroupAggregate(group, column) {
        const { widget } = column;
        const fields = this.ctx.getFields();
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
    }

    /**
     * @param {Event} ev
     * @param {any} value
     * @param {string} fieldName
     */
    openMultiCurrencyPopover(ev, value, fieldName) {
        if (value === undefined) {
            return;
        }
        if (!this.multiCurrencyPopover.isOpen) {
            this.multiCurrencyPopover.open(/** @type {HTMLElement} */ (ev.target), {
                currencyIds: Array.from(this.getFieldCurrencies(fieldName)),
                target: /** @type {HTMLElement} */ (ev.target),
                value,
            });
        }
    }
}

/**
 * @param {ListAggregatesContext} ctx
 * @returns {ListAggregates}
 */
export function useListAggregates(ctx) {
    const multiCurrencyPopover = usePopover(MultiCurrencyPopover, {
        position: "right",
    });
    /** @type {{ currencyRates: Record<number, any> | null, ratesFailed: boolean }} */
    const state = useState({ currencyRates: null, ratesFailed: false });
    const self = new ListAggregates(ctx, { state, multiCurrencyPopover });
    onWillStart(() => {
        if (self.hasMonetaryAggregate) {
            return self.requestCurrencyRates();
        }
    });
    return self;
}
