// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/group_postprocessor - Recursive postprocessor for web_read_group responses */

import { Domain } from "@web/core/domain";

import { makeActiveField } from "./field_metadata.js";
import { extractInfoFromGroupData } from "./field_values.js";

/** @import { RelationalModelConfig } from "./relational_model.js" */

/**
 * @typedef {object} PostprocessReadGroupDeps
 * @property {(config: RelationalModelConfig, propertyFullName: string) => Promise<void>}
 *   getPropertyDefinition Forwarded to ``RelationalModel._getPropertyDefinition``
 *   to lazily fetch the property arch the first time the user groups by it.
 * @property {Record<string, { activeFields: Record<string, any>; fields: Record<string, any> }>} groupByInfo
 *   Per-groupBy record-spec overrides, same shape as {@link buildWebReadGroupParams};
 *   passed in so the postprocessor stays decoupled from the model class.
 * @property {number} initialLimit Per-group default record limit at
 *   the deepest groupBy level.
 * @property {number} initialGroupsLimit Per-group default group limit
 *   when there are still nested groupBy axes below this level.
 * @property {number} defaultGroupLimit Fallback when
 *   ``initialGroupsLimit`` is unset; mirrors
 *   ``RelationalModel.DEFAULT_GROUP_LIMIT``.
 */

/**
 * Postprocess a ``web_read_group`` response into the shape the client model
 * expects. Two responsibilities:
 *
 *   1. **Per-group config seeding** — every server group is mapped back to a
 *      cached ``config.groups[<value>]`` entry, seeded fresh or patched in
 *      place so reload doesn't reset pagination state the user opened
 *      manually.
 *
 *   2. **Sticky-empty insertion** — if the same query re-runs and a group
 *      drops out of the response (e.g. records moved out via kanban drag),
 *      re-insert it with empty records / zeroed aggregates so the column
 *      doesn't vanish mid-flow. Gated on the ``params`` hash matching — a
 *      fresh filter/sort starts clean.
 *
 * MUTATES ``config.groups`` and ``config.currentGroups`` (same contract as
 * the original method); returns the public ``{ groups, length }`` shape.
 *
 * @param {RelationalModelConfig} config
 * @param {{ groups: any[]; length: number }} response
 * @param {PostprocessReadGroupDeps} deps
 * @returns {Promise<{ groups: any[]; length: number }>}
 */
export async function postprocessReadGroup(config, response, deps) {
    const {
        getPropertyDefinition,
        groupByInfo,
        initialLimit,
        initialGroupsLimit,
        defaultGroupLimit,
    } = deps;
    let { groups, length } = response;

    const commonConfig = {
        resModel: config.resModel,
        fields: config.fields,
        activeFields: config.activeFields,
        fieldsToAggregate: config.fieldsToAggregate,
        offset: 0,
    };

    const extractGroups = async (currentConfig, groupsData) => {
        const groupByFieldName = currentConfig.groupBy[0].split(":")[0];
        if (groupByFieldName.includes(".")) {
            // Property-field groupby — load the dynamic definition
            // (and add the parent properties field to activeFields so
            // a drag-and-drop doesn't need to refetch the value).
            if (!config.fields[groupByFieldName]) {
                await getPropertyDefinition(config, groupByFieldName);
            }
            const propertiesFieldName = groupByFieldName.split(".")[0];
            if (!config.activeFields[propertiesFieldName]) {
                config.activeFields[propertiesFieldName] = makeActiveField();
            }
        }
        const nextLevelGroupBy = currentConfig.groupBy.slice(1);
        const out = [];

        let groupRecordConfig;
        if (groupByInfo[groupByFieldName]) {
            groupRecordConfig = {
                ...groupByInfo[groupByFieldName],
                resModel: currentConfig.fields[groupByFieldName].relation,
                context: {},
            };
        }

        for (const groupData of groupsData) {
            const group = extractInfoFromGroupData(
                groupData,
                currentConfig.groupBy,
                currentConfig.fields,
                currentConfig.domain,
            );
            if (!currentConfig.groups[group.value]) {
                currentConfig.groups[group.value] = {
                    ...commonConfig,
                    groupByFieldName,
                    extraDomain: false,
                    value: group.value,
                    list: {
                        ...commonConfig,
                        groupBy: nextLevelGroupBy,
                        groups: {},
                        limit: !nextLevelGroupBy.length
                            ? initialLimit
                            : initialGroupsLimit || defaultGroupLimit,
                    },
                };
            }

            const groupConfig = currentConfig.groups[group.value];
            groupConfig.list.orderBy = currentConfig.orderBy;
            groupConfig.initialDomain = group.domain;
            if (groupConfig.extraDomain) {
                groupConfig.list.domain = Domain.and([
                    group.domain,
                    groupConfig.extraDomain,
                ]).toList();
            } else {
                groupConfig.list.domain = group.domain;
            }
            const context = {
                ...currentConfig.context,
                [`default_${groupByFieldName}`]: group.serverValue,
            };
            groupConfig.list.context = context;
            groupConfig.context = context;
            if (nextLevelGroupBy.length) {
                groupConfig.isFolded = !("__groups" in groupData);
                if (!groupConfig.isFolded) {
                    const { groups: nested, length: nestedLength } = groupData.__groups;
                    group.groups = await extractGroups(groupConfig.list, nested);
                    group.length = nestedLength;
                } else {
                    group.groups = [];
                }
            } else {
                groupConfig.isFolded = !("__records" in groupData);
                if (!groupConfig.isFolded) {
                    group.records = groupData.__records;
                    group.length = groupData.__count;
                } else {
                    group.records = [];
                }
            }
            if (Object.hasOwn(groupData, "__offset")) {
                groupConfig.list.offset = groupData.__offset;
            }
            if (groupRecordConfig) {
                groupConfig.record = {
                    ...groupRecordConfig,
                    resId: group.value ?? false,
                };
            }
            out.push(group);
        }

        return out;
    };

    groups = await extractGroups(config, groups);

    // Sticky-empty pass (see docstring): reloading the same (domain, groupBy,
    // offset, limit, orderBy) tuple re-injects any group that dropped out of
    // the response, so the UI doesn't lose the column mid-flow.
    const params = JSON.stringify([
        config.domain,
        config.groupBy,
        config.offset,
        config.limit,
        config.orderBy,
    ]);
    if (config.currentGroups && config.currentGroups.params === params) {
        const currentGroups = config.currentGroups.groups;
        // Precompute a ``key -> index`` map over the freshly-built groups once,
        // so the cursor advance below is O(1) per surviving group instead of a
        // linear ``findIndex`` scan (the pass was O(G²) ``JSON.stringify`` work
        // per grouped reload). Group values are unique within a single
        // ``web_read_group`` response, so the first index is the only index.
        const newGroupIndex = new Map();
        groups.forEach((g, i) => {
            const key = JSON.stringify(g.value);
            if (!newGroupIndex.has(key)) {
                newGroupIndex.set(key, i);
            }
        });
        // Insert each dropped group right after the previous surviving
        // group's position in the MERGED array — the old group's index is
        // stale as soon as one group has been re-inserted or the response
        // comes back with fewer/reordered groups.
        let cursor = 0;
        for (const group of currentGroups) {
            const key = JSON.stringify(group.value);
            if (newGroupIndex.has(key)) {
                // Mirror the old ``findIndex(i >= cursor)`` guard: only advance
                // past a surviving group at or after the cursor (an earlier
                // index was already consumed).
                const index = newGroupIndex.get(key);
                if (index >= cursor) {
                    cursor = index + 1;
                }
                continue;
            }
            if (config.groups[group.value]) {
                const aggregates = { ...group.aggregates };
                for (const aggKey of Object.keys(aggregates)) {
                    // ``array_agg_distinct`` returns an array; everything else
                    // collapses to a numeric zero.
                    aggregates[aggKey] = Array.isArray(aggregates[aggKey]) ? [] : 0;
                }
                groups.splice(cursor, 0, {
                    ...group,
                    count: 0,
                    length: 0,
                    records: [],
                    aggregates,
                });
                cursor++;
            }
        }
    }
    config.currentGroups = { params, groups };

    return { groups, length };
}
