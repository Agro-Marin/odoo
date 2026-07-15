// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/read_group_builder - Pure assembly of the kwargs payload sent to web_read_group */

import { pick } from "@web/core/utils/collections/objects";
import { orderByToString } from "@web/core/utils/order_by";

import { getBasicEvalContext } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import { getAggregateSpecifications, getGroupServerValue } from "./field_values.js";

/** @import { RelationalModelConfig } from "./relational_model.js" */

/**
 * Walk the cached ``config.groups`` tree and emit the ``opening_info``
 * descriptor the server uses to decide which groups to expand and how many
 * records to fetch per group, mirroring each group's last known
 * limit/offset/folded state. Recursive: nested groups produce nested
 * ``groups: [...]`` arrays.
 *
 * @param {Record<string, any>} groups
 * @returns {Array<Record<string, any>>}
 */
function buildOpeningInfo(groups) {
    return Object.values(groups).map((group) => {
        const field = group.fields[group.groupByFieldName];
        const value =
            field.type !== "many2many"
                ? getGroupServerValue(field, group.value)
                : group.value;
        if (group.isFolded) {
            return { value, folded: group.isFolded };
        }
        return {
            value,
            folded: group.isFolded,
            limit: group.list.limit,
            offset: group.list.offset,
            progressbar_domain: group.extraDomain,
            groups: group.list.groups && buildOpeningInfo(group.list.groups),
        };
    });
}

/**
 * @typedef {object} WebReadGroupBuilderDeps
 * @property {Record<string, { activeFields: Record<string, any>; fields: Record<string, any> }>} groupByInfo
 *   Per-groupBy override map; when set for an axis, its nested record is
 *   read via the override's spec instead of the parent config's.
 * @property {number} initialLimit Per-group record limit sent server-side
 *   as ``unfold_read_default_limit``.
 */

/**
 * Assemble the ``aggregates`` array and ``kwargs`` dict for a
 * ``web_read_group`` RPC, piped by the caller into
 * ``orm.webReadGroup(model, domain, groupBy, aggregates, params)``.
 * Pure function: ``config`` supplies every per-call value, ``deps`` injects
 * the two model-level properties this assembly depends on.
 *
 * @param {RelationalModelConfig} config
 * @param {WebReadGroupBuilderDeps} deps
 * @returns {{ aggregates: string[]; params: Record<string, any> }}
 */
export function buildWebReadGroupParams(config, deps) {
    const { groupByInfo, initialLimit } = deps;
    const aggregates = getAggregateSpecifications(
        pick(config.fields, ...config.fieldsToAggregate),
    );
    const currentGroupInfos = buildOpeningInfo(config.groups);
    const { activeFields, fields } = config;
    const evalContext = getBasicEvalContext(config);
    const unfoldReadSpecification = getFieldsSpec(activeFields, fields, evalContext);

    const groupByReadSpecification = {};
    for (const groupBy of config.groupBy) {
        const groupInfo = groupByInfo[groupBy];
        if (groupInfo) {
            const { activeFields: gAf, fields: gF } = groupInfo;
            groupByReadSpecification[groupBy] = getFieldsSpec(gAf, gF, evalContext);
        }
    }

    const params = {
        limit: config.limit !== Number.MAX_SAFE_INTEGER ? config.limit : undefined,
        offset: config.offset,
        order: orderByToString(config.orderBy),
        auto_unfold: config.openGroupsByDefault,
        opening_info: currentGroupInfos,
        unfold_read_specification: unfoldReadSpecification,
        unfold_read_default_limit: initialLimit,
        groupby_read_specification: groupByReadSpecification,
        context: { read_group_expand: true, ...config.context },
    };
    return { aggregates, params };
}
