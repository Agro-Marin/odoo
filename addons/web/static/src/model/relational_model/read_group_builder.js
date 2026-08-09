// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/read_group_builder */

import { orderByToString } from "@web/core/utils/order_by";

import { getSpecEvalContext } from "./field_context.js";
import { getFieldsSpec } from "./field_spec.js";
import { getAggregateSpecifications, getGroupServerValue } from "./field_values.js";

/** @import { RelationalModelConfig } from "./relational_model.js" */

/**
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
 * @property {number} initialLimit
 */

/**
 * `config.groups` is established by `loadGroupedList` before this runs.
 *
 * @param {RelationalModelConfig} config
 * @param {WebReadGroupBuilderDeps} deps
 * @returns {{ aggregates: string[]; params: Record<string, any> }}
 */
export function buildWebReadGroupParams(config, deps) {
    const { groupByInfo, initialLimit } = deps;
    const aggregates = getAggregateSpecifications(
        config.fields,
        config.fieldsToAggregate,
    );
    const currentGroupInfos = buildOpeningInfo(
        /** @type {Record<string, any>} */ (config.groups),
    );
    const { activeFields, fields } = config;
    const evalContext = getSpecEvalContext(config);
    const unfoldReadSpecification = getFieldsSpec(activeFields, fields, evalContext);

    /** @type {Record<string, any>} */
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
