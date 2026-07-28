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

export const AGGREGATABLE_FIELD_TYPES = ["float", "integer", "monetary"];

/**
 * Per-type server→client value deserializers, keyed by field type.
 * Single source shared with the value codec (``@web/core/field_codec``), whose
 * ``deserialize`` reads this same registry, so model and UI never diverge.
 * Entry signature: ``(value, field) => clientValue``; types with no entry pass
 * through unchanged (see {@link parseServerValue}).
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
            ? value.map((property) => {
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
 * Memoised specs, keyed on the field container and then on the requested
 * subset. The second level exists because the read-group REQUEST asks only for
 * ``config.fieldsToAggregate`` while the RESPONSE is decoded against the whole
 * ``config.fields`` — two different scopes over one long-lived container. The
 * subset key is the field NAMES, not the array holding them: the kanban
 * controller rebuilds ``fieldsToAggregate`` with ``.map()`` on every config, so
 * an identity key would never match.
 *
 * @type {WeakMap<object, Map<string, string[]>>}
 */
const aggregateSpecCache = new WeakMap();

/**
 * Drop the memoised aggregate specs for ``fields``. MUST be called whenever a
 * ``fields`` container is mutated IN PLACE after the memo may have been built
 * — property axes spliced in by ``RelationalModel._getPropertyDefinition`` and
 * ``record_properties.processProperties``, form-view fields merged by
 * ``StaticList.extendRecord``.
 *
 * No mutation reachable today introduces an ``aggregator``-bearing field (a
 * property definition is a user-authored JSONB blob that carries no
 * ``aggregator``), so this closes an invariant gap rather than a live bug. It
 * exists because the sibling memo in ``record_utils.js`` keyed on the same
 * mutable containers DOES have {@link invalidateModifierDependencies}, and a
 * cache whose key can change under it without an invalidation hook is a trap
 * for the next person who adds a field def with an aggregator.
 *
 * @param {Record<string, any> | any[]} fields
 */
export function invalidateAggregateSpecs(fields) {
    aggregateSpecCache.delete(fields);
}

/**
 * Build the ``aggregates`` list for a read-group: ``field:aggregator`` per
 * aggregatable field, plus the currency companions monetary sums need.
 *
 * @param {Record<string, any> | any[]} fields field defs, by name or as a list
 * @param {string[]} [fieldNames] restrict to these fields (default: all of
 *  ``fields``). Deduplicated, and names absent from ``fields`` are skipped.
 * @returns {string[]}
 */
export function getAggregateSpecifications(fields, fieldNames) {
    let byScope = aggregateSpecCache.get(fields);
    if (!byScope) {
        byScope = new Map();
        aggregateSpecCache.set(fields, byScope);
    }
    const scope = fieldNames && [...new Set(fieldNames)];
    // Tagged, not bare: an EMPTY ``fieldNames`` array is truthy and also joins
    // to "", so "aggregate nothing" and "aggregate everything" shared one memo
    // slot and each poisoned the other. A kanban with a progressbar but no
    // ``sum_field`` passes exactly that empty scope (kanban_controller's
    // ``progressBarAggregateFields`` is then ``[]``), against the same
    // long-lived ``config.fields`` the response decoding reads back with no
    // scope at all.
    const scopeKey = scope ? `s:${scope.join(",")}` : "*";
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
 * The domain-independent part of {@link extractInfoFromGroupData}: a group's
 * aggregate values and its server-side value.
 *
 * Consumers that only bucket aggregates per group (the kanban progress bars)
 * use this instead, so they stop paying for a per-group ``__domain`` — two
 * Domain constructions plus an AST evaluation each — that they discard.
 *
 * @param {Object} groupData
 * @param {string[]} groupBy
 * @param {Object} fields
 * @returns {{ aggregates: Object, serverValue: any }}
 */
export function extractAggregatesFromGroupData(groupData, groupBy, fields) {
    const groupByField = fields[groupBy[0].split(":")[0]];
    const value = getValueFromGroupData(groupByField, groupData[groupBy[0]]);
    return {
        aggregates: getAggregatesFromGroupData(groupData, fields),
        serverValue: getGroupServerValue(groupByField, value),
    };
}

/**
 * Extract useful information from a group data returned by a call to webReadGroup.
 *
 * @param {Object} groupData
 * @param {string[]} groupBy
 * @param {Object} fields
 * @param {any} domain search domain the groups were read under; combined with
 *   each group's ``__extra_domain`` into ``info.domain``
 * @returns {Object}
 */
export function extractInfoFromGroupData(groupData, groupBy, fields, domain) {
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
    info.aggregates = getAggregatesFromGroupData(groupData, fields);
    info.values = groupData.__values;
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
 * Onchanges may reference records we never loaded (e.g. a page not yet fetched);
 * we still must resend their update commands on save, translated from "unity
 * read" format to the server write format (e.g. many2one
 * { id: 3, display_name: "Marc" } => 3).
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
            // These payloads come from onchange commands for records the client
            // never loaded, so the field universe they name is the SERVER's,
            // not this view's. Pass an unknown field through untransformed
            // rather than dereferencing ``undefined``: dropping it would lose
            // a value the server asked us to write, and ``_mockRead`` in
            // sample_server takes the same "unknown field is not fatal" line.
            serverValues[fieldName] = value;
            continue;
        }
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
                // didn't read the record, so we ignore it
            }
        }
        switch (field.type) {
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
