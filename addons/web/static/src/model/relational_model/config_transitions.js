// @ts-check
/** @odoo-module native */

/** @module @web/model/relational_model/config_transitions - Pure derivation of the next RelationalModelConfig from a current config + load params */

import { shallowEqual } from "@web/core/utils/collections/objects";

/** @import { RelationalModelConfig } from "./relational_model" */
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
 * Mutates a shallow copy of ``currentConfig``; nested structures
 * (``groups``, ``context``) are NOT deep-cloned since the caller's
 * overwrite semantics already cover the only paths that matter.
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
    // Always re-spread so subsequent mutations don't leak into the
    // previous config (RelationalModel holds the previous via
    // ``this.config`` until the load lands).
    config.context = { ...config.context };

    if (currentConfig.isMonoRecord) {
        config.resId = "resId" in params ? params.resId : config.resId;
        config.resIds = "resIds" in params ? params.resIds : config.resIds;
        if (!config.resIds) {
            config.resIds = config.resId ? [config.resId] : [];
        }
        if (!config.resId && config.mode !== "edit") {
            // No resId means the form is creating a new record; force
            // edit mode so the user can immediately start typing.
            config.mode = "edit";
        }
    } else {
        config.domain = "domain" in params ? params.domain : config.domain;

        config.groupBy = "groupBy" in params ? params.groupBy : config.groupBy;
        if (maxGroupByDepth) {
            config.groupBy = config.groupBy.slice(0, maxGroupByDepth);
        }
        // Apply month granularity if none explicitly given.
        // TODO: accept only explicit granularity (historical TODO preserved
        // from the source method so it doesn't go missing in the move).
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

        // Keep the cached ``groups`` dict only when the groupBy axis
        // is unchanged. A different groupBy invalidates every cached
        // sub-config — dropping the dict forces the postprocessor to
        // rebuild from scratch.
        if (!shallowEqual(config.groupBy || [], currentGroupBy || [])) {
            delete config.groups;
        }
        if (!config.groupBy.length) {
            // ``__count`` is a synthetic order-by introduced when grouping
            // by record count; meaningless on an ungrouped list.
            config.orderBy = config.orderBy.filter((order) => order.name !== "__count");
        }
    }
    if (!config.isMonoRecord && params.domain) {
        // Always reset the offset to 0 when reloading with a new
        // domain — otherwise the user lands on page N of a result
        // set whose total is smaller than N*limit.
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
            // From grouped to ungrouped or vice versa — force a limit
            // reset so the caller-supplied default kicks in (group
            // limit vs record limit are very different defaults).
            delete config.limit;
        }
    }

    return config;
}
