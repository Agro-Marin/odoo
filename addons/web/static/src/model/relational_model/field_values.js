// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
/** @import { Field } from "@web/model/types" */
import { Domain } from "@web/core/domain";
import {
    deserializeDate,
    deserializeDateTime,
    serializeDate,
    serializeDateTime,
} from "@web/core/l10n/dates";
import { x2ManyCommands } from "@web/core/network/commands";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { unique } from "@web/core/utils/collections/arrays";

const granularityToInterval = {
    hour: { hours: 1 },
    day: { days: 1 },
    week: { days: 7 },
    month: { months: 1 },
    quarter: { months: 3 },
    year: { years: 1 },
};

export const AGGREGATABLE_FIELD_TYPES = ["float", "integer", "monetary"];

const deserializers = registry.category("deserializers");
deserializers
    .add("char", (value) => value || "")
    .add("text", (value) => value || "")
    .add("html", (value) => markup(value || ""))
    .add("date", (value) => (value ? deserializeDate(value) : false))
    .add("datetime", (value) => (value ? deserializeDateTime(value) : false))
    .add("selection", (value, field) => {
        if (value === false) {
            return field.selection.some((/** @type {any} */ opt) => opt[0] === 0)
                ? 0
                : value;
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
            return false;
        }
        if (typeof value === "number") {
            return { resId: value };
        }
        return {
            resId: value.id,
            displayName: value.display_name,
        };
    })
    .add("many2one", (value) => {
        if (Array.isArray(value)) {
            return { id: value[0], display_name: value[1] };
        }
        return value;
    })
    .add("properties", (value) =>
        value
            ? value.map((/** @type {any} */ property) => {
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

/**
 * @type {WeakMap<object, Map<string, string[]>>}
 */
const aggregateSpecCache = new WeakMap();

/**
 * @param {Record<string, any> | any[]} fields
 */
export function invalidateAggregateSpecs(fields) {
    aggregateSpecCache.delete(fields);
}

/**
 * @param {Record<string, any> | any[]} fields
 * @param {string[]} [fieldNames]
 * @returns {string[]}
 */
export function getAggregateSpecifications(fields, fieldNames) {
    let byScope = aggregateSpecCache.get(fields);
    if (!byScope) {
        byScope = new Map();
        aggregateSpecCache.set(fields, byScope);
    }
    const scope = fieldNames && [...new Set(fieldNames)];
    const scopeKey = scope ? `s:${[...scope].sort().join(",")}` : "*";
    let specs = byScope.get(scopeKey);
    if (specs) {
        return specs;
    }
    const scopedFields = scope
        ? scope.filter((name) => name in fields).map((name) => fields[name])
        : Object.values(fields);
    const aggregatableFields = scopedFields
        .filter(
            (field) =>
                field.aggregator && AGGREGATABLE_FIELD_TYPES.includes(field.type),
        )
        .map((field) => `${field.name}:${field.aggregator}`);
    const currencyFields = unique(
        scopedFields
            .filter((field) => field.aggregator && field.currency_field)
            .map((field) => [
                `${field.currency_field}:array_agg_distinct`,
                `${field.name}:sum_currency`,
            ])
            .flat(),
    );
    specs = [...aggregatableFields, ...currencyFields];
    byScope.set(scopeKey, specs);
    return specs;
}

/**
 * @param {Object} groupData
 * @param {string[]} groupBy
 * @param {Object} fields
 * @param {string[]} [fieldsToAggregate]
 * @returns {{ aggregates: Object, serverValue: any }}
 */
export function extractAggregatesFromGroupData(
    groupData,
    groupBy,
    fields,
    fieldsToAggregate,
) {
    const groupByField = fields[groupBy[0].split(":")[0]];
    const value = getValueFromGroupData(groupByField, groupData[groupBy[0]]);
    return {
        aggregates: getAggregatesFromGroupData(groupData, fields, fieldsToAggregate),
        serverValue: getGroupServerValue(groupByField, value),
    };
}

/**
 * @param {Object} groupData
 * @param {string[]} groupBy
 * @param {Object} fields
 * @param {any} domain
 * @param {string[]} [fieldsToAggregate]
 * @returns {Object}
 */
export function extractInfoFromGroupData(
    groupData,
    groupBy,
    fields,
    domain,
    fieldsToAggregate,
) {
    const info = {};
    const groupByField = fields[groupBy[0].split(":")[0]];
    info.count = groupData.__count;
    info.length = info.count;
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
    info.aggregates = getAggregatesFromGroupData(groupData, fields, fieldsToAggregate);
    info.values = groupData.__values;
    return info;
}

/**
 * @param {Object} groupData
 * @param {Object} fields
 * @param {string[]} [fieldsToAggregate]
 * @returns {Object}
 */
function getAggregatesFromGroupData(groupData, fields, fieldsToAggregate) {
    const aggregates = {};
    for (const keyAggregate of getAggregateSpecifications(fields, fieldsToAggregate)) {
        if (keyAggregate in groupData) {
            const [fieldName, aggregate] = keyAggregate.split(":");
            if (aggregate === "sum_currency") {
                const currencies =
                    groupData[`${fields[fieldName].currency_field}:array_agg_distinct`];
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
            const selectionMap = Object.fromEntries(field.selection);
            return rawValue in selectionMap
                ? selectionMap[rawValue]
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
        if (!field) {
            serverValues[fieldName] = value;
            continue;
        }
        if (!withReadonly) {
            if (field.readonly) {
                continue;
            }
            if (activeField?.readonly) {
                let readonly;
                try {
                    readonly = evaluateBooleanExpr(activeField.readonly, context);
                } catch {
                    readonly = false;
                }
                if (readonly) {
                    continue;
                }
            }
        }
        switch (field.type) {
            case "one2many":
            case "many2many":
                value = value.map((/** @type {any} */ c) => {
                    if (c[0] === CREATE || c[0] === UPDATE) {
                        const related = activeField?.related;
                        if (!related) {
                            return c;
                        }
                        return [
                            c[0],
                            c[1],
                            fromUnityToServerValues(
                                c[2],
                                related.fields,
                                related.activeFields,
                                { withReadonly },
                            ),
                        ];
                    }
                    if (c[0] === LINK && c[2] && typeof c[2] === "object") {
                        return [LINK, c[1], false];
                    }
                    return c;
                });
                break;
            case "many2one":
                value = value ? value.id : false;
                break;
            case "reference":
                value =
                    value?.resModel && value.resId
                        ? `${value.resModel},${value.resId}`
                        : false;
                break;
        }
        serverValues[fieldName] = value;
    }
    return serverValues;
}
