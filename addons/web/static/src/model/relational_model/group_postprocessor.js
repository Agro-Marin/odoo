// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/group_postprocessor */

import { Domain } from "@web/core/domain";

import { makeActiveField } from "./field_metadata.js";
import { extractInfoFromGroupData } from "./field_values.js";

/** @import { RelationalModelConfig } from "./relational_model.js" */

/**
 * @typedef {object} PostprocessReadGroupDeps
 * @property {(config: RelationalModelConfig, propertyFullName: string) => Promise<void>} getPropertyDefinition
 * @property {Record<string, { activeFields: Record<string, any>; fields: Record<string, any> }>} groupByInfo
 * @property {number} initialLimit
 * @property {number} initialGroupsLimit
 * @property {number} defaultGroupLimit
 */

/**
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
                currentConfig.fieldsToAggregate,
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

    const params = JSON.stringify([
        config.domain,
        config.groupBy,
        config.offset,
        config.limit,
        config.orderBy,
    ]);
    if (config.currentGroups && config.currentGroups.params === params) {
        const currentGroups = /** @type {any[]} */ (config.currentGroups.groups);
        const mergedKeys = groups.map((g) => JSON.stringify(g.value));
        const survivingKeys = new Set(mergedKeys);
        let cursor = 0;
        for (const group of currentGroups) {
            const key = JSON.stringify(group.value);
            if (survivingKeys.has(key)) {
                cursor = Math.max(cursor, mergedKeys.indexOf(key) + 1);
                continue;
            }
            if (/** @type {Record<string, any>} */ (config.groups)[group.value]) {
                const aggregates = { ...group.aggregates };
                for (const aggKey of Object.keys(aggregates)) {
                    aggregates[aggKey] = Array.isArray(aggregates[aggKey]) ? [] : 0;
                }
                groups.splice(cursor, 0, {
                    ...group,
                    count: 0,
                    length: 0,
                    records: [],
                    groups: [],
                    aggregates,
                });
                mergedKeys.splice(cursor, 0, key);
                cursor++;
            }
        }
    }
    config.currentGroups = { params, groups };

    return { groups, length };
}
