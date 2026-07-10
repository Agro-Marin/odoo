// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/field_values - Server value parsing, aggregation constants, and default value helpers */

import { markup } from "@odoo/owl";
/** @import { Field } from "@web/model/types" */
import { Domain } from "@web/core/domain";
import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { unique } from "@web/core/utils/collections/arrays";

import { x2ManyCommands } from "./commands.js";

const granularityToInterval = {
    hour: { hours: 1 },
    day: { days: 1 },
    week: { days: 7 },
    month: { months: 1 },
    quarter: { months: 3 },
    year: { years: 1 },
};

export const AGGREGATABLE_FIELD_TYPES = ["float", "integer", "monetary"]; // types that can be aggregated in grouped views

/**
 * Per-type server→client value deserializers, keyed by field type.
 *
 * This is the single source for "how a server value becomes a client value",
 * shared with the value codec (``@web/core/field_codec``): the codec's
 * ``deserialize`` reads this same registry, so model and UI can never diverge.
 * Each entry is ``(value, field) => clientValue``; types with no entry pass
 * the value through unchanged (see {@link parseServerValue}).
 */
const deserializers = registry.category("deserializers");
deserializers
    .add("char", (value) => value || "")
    .add("text", (value) => value || "")
    .add("html", (value) => markup(value || ""))
    .add("date", (value) => (value ? deserializeDate(value) : false))
    .add("datetime", (value) => (value ? deserializeDateTime(value) : false))
    .add("selection", (value, field) => {
        if (value === false) {
            // process selection: convert false to 0, if 0 is a valid key
            return field.selection.some((opt) => opt[0] === 0) ? 0 : value;
        }
        return value;
    })
    .add("reference", (value) => {
        if (value === false) {
            return false;
        }
        return {
            resId: value.id.id,
            resModel: value.id.model,
            displayName: value.display_name,
        };
    })
    .add("many2one_reference", (value) => {
        if (value === 0) {
            // unset many2one_reference fields' value is 0
            return false;
        }
        if (typeof value === "number") {
            // many2one_reference fetched without "fields" key in spec -> only returns the id
            return { resId: value };
        }
        return {
            resId: value.id,
            displayName: value.display_name,
        };
    })
    .add("many2one", (value) => {
        if (Array.isArray(value)) {
            // Used for web_read_group, where the value is an array of [id, display_name]
            return { id: value[0], display_name: value[1] };
        }
        return value;
    })
    .add("properties", (value) =>
        value
            ? value.map((property) => {
                  // Shallow-clone to avoid mutating the server response object
                  property = { ...property };
                  if (property.value !== undefined) {
                      property.value = parseServerValue(
                          property,
                          property.value ?? false,
                      );
                  }
                  if (property.default !== undefined) {
                      property.default = parseServerValue(
                          property,
                          property.default ?? false,
                      );
                  }
                  return property;
              })
            : [],
    );

/**
 * @protected
 * @param {Field} field
 * @param {any} value
 * @returns {any}
 */
export function parseServerValue(field, value) {
    return deserializers.get(field.type, (v) => v)(value, field);
}

// The spec list depends only on the fields map, which is invariant across a
// load: memoize per fields object so the response path doesn't re-derive it
// once per group per level (O(groups × totalFields) of pure recomputation).
const aggregateSpecCache = new WeakMap();

export function getAggregateSpecifications(fields) {
    let specs = aggregateSpecCache.get(fields);
    if (specs) {
        return specs;
    }
    const aggregatableFields = Object.values(fields)
        .filter(
            (field) =>
                field.aggregator && AGGREGATABLE_FIELD_TYPES.includes(field.type),
        )
        .map((field) => `${field.name}:${field.aggregator}`);
    const currencyFields = unique(
        Object.values(fields)
            .filter((field) => field.aggregator && field.currency_field)
            .map((field) => [
                `${field.currency_field}:array_agg_distinct`,
                `${field.name}:sum_currency`,
            ])
            .flat(),
    );
    specs = [...aggregatableFields, ...currencyFields];
    aggregateSpecCache.set(fields, specs);
    return specs;
}

/**
 * Extract useful information from a group data returned by a call to webReadGroup.
 *
 * @param {Object} groupData
 * @param {string[]} groupBy
 * @param {Object} fields
 * @returns {Object}
 */
export function extractInfoFromGroupData(groupData, groupBy, fields, domain) {
    const info = {};
    const groupByField = fields[groupBy[0].split(":")[0]];
    info.count = groupData.__count;
    info.length = info.count; // Alias: DynamicRecordList._updateCount reads .length
    info.domain = Domain.and([domain, groupData.__extra_domain]).toList();
    info.rawValue = groupData[groupBy[0]];
    info.value = getValueFromGroupData(groupByField, info.rawValue);
    if (["date", "datetime"].includes(groupByField.type) && info.value) {
        const granularity = groupBy[0].split(":")[1];
        info.range = {
            from: info.value,
            to: info.value.plus(granularityToInterval[granularity]),
        };
    }
    info.displayName = getDisplayNameFromGroupData(groupByField, info.rawValue);
    info.serverValue = getGroupServerValue(groupByField, info.value);
    info.aggregates = getAggregatesFromGroupData(groupData, fields);
    info.values = groupData.__values; // Extra data of the relational groupby field record
    return info;
}

/**
 * @param {Object} groupData
 * @returns {Object}
 */
function getAggregatesFromGroupData(groupData, fields) {
    const aggregates = {};
    for (const keyAggregate of getAggregateSpecifications(fields)) {
        if (keyAggregate in groupData) {
            const [fieldName, aggregate] = keyAggregate.split(":");
            if (aggregate === "sum_currency") {
                const currencies =
                    groupData[`${fields[fieldName].currency_field}:array_agg_distinct`];
                // The currency aggregate may be absent/false for empty
                // expanded groups — only skip on a confirmed single currency.
                if (currencies?.length === 1) {
                    continue;
                }
            }
            aggregates[fieldName] = groupData[keyAggregate];
        }
    }
    return aggregates;
}

/**
 * @param {any} field
 * @param {any} rawValue
 * @returns {string}
 */
function getDisplayNameFromGroupData(field, rawValue) {
    switch (field.type) {
        case "selection": {
            // A falsy raw value has no entry in the selection map; fall back to
            // the falsy label like every other field type instead of returning
            // ``undefined``.
            return rawValue
                ? Object.fromEntries(field.selection)[rawValue]
                : field.falsy_value_label || _t("None");
        }
        case "boolean": {
            return rawValue ? _t("Yes") : _t("No");
        }
        case "integer": {
            return rawValue ? String(rawValue) : "0";
        }
        case "many2one":
        case "many2many":
        case "date":
        case "datetime":
        case "tags": {
            return (rawValue && rawValue[1]) || field.falsy_value_label || _t("None");
        }
    }
    return rawValue ? String(rawValue) : field.falsy_value_label || _t("None");
}

/**
 * @param {any} field
 * @param {any} value
 * @returns {any}
 */
export function getGroupServerValue(field, value) {
    switch (field.type) {
        case "many2many": {
            return value ? [value] : false;
        }
        case "datetime": {
            return value ? serializeDateTime(value) : false;
        }
        case "date": {
            return value ? serializeDate(value) : false;
        }
        default: {
            return value ?? false;
        }
    }
}

/**
 * @param {Field} field
 * @param {any} rawValue
 * @returns {any}
 */
function getValueFromGroupData(field, rawValue) {
    if (["date", "datetime"].includes(field.type)) {
        if (!rawValue) {
            return false;
        }
        return parseServerValue(field, rawValue[0]);
    }
    const value = parseServerValue(field, rawValue);
    if (field.type === "many2one") {
        return value?.id;
    }
    if (field.type === "many2many") {
        return value ? value[0] : false;
    }
    if (field.type === "tags") {
        return value ? value[0] : false;
    }
    return value;
}

/**
 * Onchanges sometimes return update commands for records we don't know (e.g. if
 * they are on a page we haven't loaded yet). We may actually never load them.
 * When this happens, we must still be able to send back those commands to the
 * server when saving. However, we can't send the commands exactly as we received
 * them, since the values they contain have been "unity read". The purpose of this
 * function is to transform field values from the unity format to the format
 * expected by the server for a write.
 * For instance, for a many2one: { id: 3, display_name: "Marc" } => 3.
 * @param {Record<string, unknown>} values
 * @param {Record<string, object>} fields
 * @param {Record<string, object>} activeFields
 * @param {{ withReadonly?: boolean, context?: Record<string, unknown> }} [options]
 */
export function fromUnityToServerValues(
    values,
    fields,
    activeFields,
    { withReadonly, context } = {},
) {
    const { CREATE, UPDATE, LINK } = x2ManyCommands;
    const serverValues = {};
    for (const fieldName of Object.keys(values)) {
        /** @type {any} */
        let value = values[fieldName];
        const field = fields[fieldName];
        const activeField = activeFields[fieldName];
        if (!withReadonly) {
            if (field.readonly) {
                continue;
            }
            try {
                if (evaluateExpr(activeField.readonly, context)) {
                    continue;
                }
            } catch {
                // if the readonly expression depends on other fields, we can't evaluate it as we
                // didn't read the record, so we simply ignore it
            }
        }
        switch (fields[fieldName].type) {
            case "one2many":
            case "many2many":
                value = value.map((c) => {
                    if (c[0] === CREATE || c[0] === UPDATE) {
                        const _fields = activeField.related.fields;
                        const _activeFields = activeField.related.activeFields;
                        return [
                            c[0],
                            c[1],
                            fromUnityToServerValues(c[2], _fields, _activeFields, {
                                withReadonly,
                            }),
                        ];
                    }
                    // Strip server-enriched record data from LINK commands.
                    // Onchange responses include cached data as the third element
                    // (e.g. [4, id, {display_name: ...}]) to avoid extra reads,
                    // but this must not be sent back on save.
                    if (c[0] === LINK && c[2] && typeof c[2] === "object") {
                        return [LINK, c[1], false];
                    }
                    return c;
                });
                break;
            case "many2one":
                value = value ? value.id : false;
                break;
            // case "reference":
            //     // TODO
            //     break;
        }
        serverValues[fieldName] = value;
    }
    return serverValues;
}
