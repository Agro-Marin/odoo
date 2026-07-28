// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/config_transitions - Pure derivation of the next RelationalModelConfig from a current config + load params */

import { shallowEqual } from "@web/core/utils/collections/objects";

/** @import { RelationalModelConfig } from "./relational_model.js" */
/** @import { SearchParams } from "@web/model/types" */

/**
 * @typedef {object} ConfigTransitionDeps
 * @property {number} [maxGroupByDepth] Cap on the number of stacked
 *   groupbys. Read from ``RelationalModel.maxGroupByDepth`` — pass it
 *   in rather than reaching back into the model instance so the
 *   transformer is unit-testable in isolation.
 * @property {any[]} [defaultOrderBy] Fallback order applied when the
 *   caller supplied no ``orderBy`` and the current config has no
 *   active order either. ``RelationalModel.defaultOrderBy`` is the
 *   canonical source.
 * @property {boolean} hasRoot Whether the model already has a loaded
 *   root datapoint. Controls the offset-reset path: when loading
 *   into an existing tree we walk it depth-first; on first load
 *   there is nothing to reset.
 */

/**
 * Build the next ``RelationalModelConfig`` from a current one plus a
 * partial parameter bag. Mirrors the historical
 * ``RelationalModel._getNextConfig`` contract.
 *
 * Two branches: **MonoRecord** (``resId``/``resIds`` propagation, plus
 * "switch to edit mode when no resId" for the create flow
 * (``record.load({ resId: false })``)) and **List /
 * grouped** (domain/groupBy/orderBy plumbing, max-depth clipping,
 * default-month granularity for date/datetime groupbys, and an
 * offset-reset on domain change so pagination doesn't strand the user on
 * an empty page).
 *
 * Mutates a shallow copy of ``currentConfig``. ``context`` is re-spread and
 * the ``groups`` tree is structurally cloned (see {@link cloneGroupTree}):
 * the result is a *candidate* config that a load may freely mutate
 * (``postprocessReadGroup``, offset resets) without leaking into the
 * committed config a superseded load would otherwise clobber.
 *
 * Async work (``_getPropertyDefinition``) is deliberately NOT done here —
 * that lives in {@link postprocessReadGroup}, which runs after the RPC.
 *
 * @param {RelationalModelConfig} currentConfig
 * @param {Partial<SearchParams>} params
 * @param {ConfigTransitionDeps} deps
 * @returns {RelationalModelConfig}
 */
export function computeNextConfig(currentConfig, params, deps) {
    const { maxGroupByDepth, defaultOrderBy, hasRoot } = deps;
    const currentGroupBy = currentConfig.groupBy;
    const config = { ...currentConfig };

    config.context = "context" in params ? params.context : config.context;
    config.context = { ...config.context };

    if (currentConfig.isMonoRecord) {
        config.resId = "resId" in params ? params.resId : config.resId;
        config.resIds = "resIds" in params ? params.resIds : config.resIds;
        if (!config.resIds) {
            config.resIds = config.resId ? [config.resId] : [];
        }
        if (!config.resId && config.mode !== "edit") {
            config.mode = "edit";
        }
    } else {
        config.domain = "domain" in params ? params.domain : config.domain;

        config.groupBy = "groupBy" in params ? params.groupBy : config.groupBy;
        if (maxGroupByDepth) {
            config.groupBy = config.groupBy.slice(0, maxGroupByDepth);
        }
        config.groupBy = config.groupBy.map((g) => {
            if (
                g in config.fields &&
                ["date", "datetime"].includes(config.fields[g].type)
            ) {
                return `${g}:month`;
            }
            return g;
        });

        config.orderBy = "orderBy" in params ? params.orderBy : config.orderBy;
        if (!config.orderBy.length) {
            config.orderBy = currentConfig.orderBy || [];
        }
        if (defaultOrderBy && !config.orderBy.length) {
            config.orderBy = defaultOrderBy;
        }

        if (!shallowEqual(config.groupBy || [], currentGroupBy || [])) {
            delete config.groups;
        } else if (config.groups) {
            config.groups = cloneGroupTree(config.groups);
        }
        if (!config.groupBy.length) {
            config.orderBy = config.orderBy.filter((order) => order.name !== "__count");
        }
    }
    if (!config.isMonoRecord && params.domain) {
        const resetOffset = (cfg) => {
            cfg.offset = 0;
            for (const group of Object.values(cfg.groups || {})) {
                resetOffset(group.list);
            }
        };
        if (hasRoot) {
            resetOffset(config);
        }
        if (!!config.groupBy.length !== !!currentGroupBy?.length) {
            delete config.limit;
        }
    }

    return config;
}

/**
 * Structurally clone a ``config.groups`` tree so a candidate config owns its
 * own mutable group containers. Copied per group: the entry object, its
 * ``list`` sub-config, its optional ``record`` sub-config, and (recursively)
 * the nested ``list.groups`` dict. Shared immutable references — ``fields``,
 * ``activeFields``, ``fieldsToAggregate`` — are kept as-is; the postprocessor
 * only ever *assigns* fresh ``domain``/``context``/``orderBy`` values onto the
 * containers, so container-level copies are sufficient isolation.
 *
 * Load-bearing for concurrency: data is loaded against candidate configs
 * (``RelationalModel.load`` / ``_reloadWithConfig``) and only committed on
 * success. ``KeepLast`` drops a superseded load's *result* but cannot stop its
 * continuation — ``postprocessReadGroup`` still runs when the stale RPC lands,
 * and without this clone it would rewrite the committed groups in place.
 *
 * @param {Record<string, any>} groups
 * @returns {Record<string, any>}
 */
export function cloneGroupTree(groups) {
    /** @type {Record<string, any>} */
    const cloned = {};
    for (const [value, groupConfig] of Object.entries(groups)) {
        cloned[value] = {
            ...groupConfig,
            list: {
                ...groupConfig.list,
                groups: groupConfig.list?.groups
                    ? cloneGroupTree(groupConfig.list.groups)
                    : groupConfig.list?.groups,
            },
        };
        if (groupConfig.record) {
            cloned[value].record = { ...groupConfig.record };
        }
    }
    return cloned;
}
