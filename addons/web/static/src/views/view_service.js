// @ts-check
/** @odoo-module native */

/** @module @web/views/view_service */

import { RpcEvent } from "@web/core/events";
import { onModelMutation } from "@web/core/network/model_mutation";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";

/**
 * @typedef {Object} IrFilter
 * @property {[number, string] | false} user_id
 * @property {string} sort
 * @property {string} context
 * @property {string} name
 * @property {string} domain
 * @property {number} id
 * @property {boolean} is_default
 * @property {string} model_id
 * @property {[number, string] | false} action_id
 * @property {number | false} embedded_action_id
 * @property {number | false} embedded_parent_res_id
 */

/**
 * @typedef {Object} ViewDescription
 * @property {string} arch
 * @property {number|false} id
 * @property {number|null} [custom_view_id]
 * @property {Object} [actionMenus]
 * @property {IrFilter[]} [irFilters]
 */

/**
 * @typedef {Object} LoadViewsParams
 * @property {string} resModel
 * @property {[number, string][]} views
 * @property {Object} context
 */

/**
 * @typedef {Object} LoadViewsOptions
 * @property {number|false} actionId
 * @property {boolean} loadActionMenus
 * @property {boolean} loadIrFilters
 */

/** @typedef {Record<string, ViewDescription>} ViewDescriptions */

export const viewService = {
    dependencies: ["orm"],
    async: ["loadViews"],
    start(env, { orm }) {
        const GET_VIEWS_MODELS = [
            "ir.ui.view",
            "ir.filters",
            "ir.actions.act_window",
            "ir.actions.report",
            "ir.actions.server",
            "ir.model.fields",
        ];
        onModelMutation(GET_VIEWS_MODELS, () => {
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "get_views");
        });

        /**
         * @param {LoadViewsParams} params
         * @param {LoadViewsOptions} [options={}]
         * @returns {Promise<ViewDescriptions>}
         */
        async function loadViews(params, /** @type {any} */ options = {}) {
            const { context, resModel, views } = params;
            const loadViewsOptions = {
                action_id: options.actionId || false,
                embedded_action_id: options.embeddedActionId || false,
                embedded_parent_res_id: options.embeddedParentResId || false,
                load_filters: options.loadIrFilters || false,
                toolbar:
                    (!context?.disable_toolbar && options.loadActionMenus) || false,
            };
            for (const key of Object.keys(options)) {
                if (
                    ![
                        "actionId",
                        "embeddedActionId",
                        "embeddedParentResId",
                        "loadIrFilters",
                        "loadActionMenus",
                    ].includes(key)
                ) {
                    loadViewsOptions[key] = options[key];
                }
            }
            if (env.isSmall) {
                loadViewsOptions.mobile = true;
            }
            if (env.debug) {
                loadViewsOptions.debug = true;
            }
            const filteredContext = Object.fromEntries(
                Object.entries(context || {}).filter(
                    ([k, v]) => k === "lang" || k.endsWith("_view_ref"),
                ),
            );

            const result = await orm
                .cache({ type: "disk" })
                .retry(1)
                .call(resModel, "get_views", [], {
                    context: filteredContext,
                    views,
                    options: loadViewsOptions,
                });
            /** @type {any} */
            const viewDescriptions = {
                fields: result.models[resModel].fields,
                relatedModels: result.models,
                views: {},
            };
            for (const viewType of Object.keys(result.views)) {
                const { arch, toolbar, id, filters, custom_view_id } =
                    result.views[viewType];
                const viewDescription = { arch, id, custom_view_id };
                if (toolbar) {
                    viewDescription.actionMenus = toolbar;
                }
                if (filters) {
                    viewDescription.irFilters = filters;
                }
                viewDescriptions.views[viewType] = viewDescription;
            }
            return viewDescriptions;
        }
        return { loadViews };
    },
};

registry.category("services").add("view", viewService);
