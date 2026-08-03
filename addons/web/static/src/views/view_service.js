// @ts-check
/** @odoo-module native */

/** @module @web/views/view_service */

import { RpcEvent } from "@web/core/events";
import { onModelMutation, UPDATE_METHODS } from "@web/core/network/model_mutation";
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

/**
 * Models whose mutation invalidates a cached `get_views`. A view description is
 * derived from all of them, so a write to any one makes the cache stale.
 */
const GET_VIEWS_MODELS = [
    "ir.ui.view",
    "ir.filters",
    "ir.actions.act_window",
    "ir.actions.report",
    "ir.actions.server",
    "ir.model.fields",
];

/**
 * The `view` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * The closure published `{ loadViews }` and there is nothing else to keep
 * private, so no method needed underscoring here (hazard 6). `GET_VIEWS_MODELS`
 * moved to module scope: it is a constant, and rebuilding the array on every
 * `start()` said otherwise.
 */
export class ViewService {
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     */
    constructor(env, { orm }) {
        this.env = env;
        this.orm = orm;
        // `create_filter` is `ir.filters`' dedicated favorite-creation RPC, not a
        // plain `create`, so it is not in the default UPDATE_METHODS -- yet it
        // makes a cached `get_views` (which carries `ir.filters`) stale just the
        // same. Watching it here keeps every `get_views` invalidation in this one
        // declarative place, instead of the favorites mixin hand-firing the same
        // CLEAR_CACHES after its own `create_filter` call.
        onModelMutation(
            GET_VIEWS_MODELS,
            () => {
                rpcBus.trigger(RpcEvent.CLEAR_CACHES, "get_views");
            },
            { methods: [...UPDATE_METHODS, "create_filter"] },
        );
    }

    /**
     * @param {LoadViewsParams} params
     * @param {LoadViewsOptions} [options={}]
     * @returns {Promise<ViewDescriptions>}
     */
    async loadViews(params, /** @type {any} */ options = {}) {
        const { context, resModel, views } = params;
        const loadViewsOptions = {
            action_id: options.actionId || false,
            embedded_action_id: options.embeddedActionId || false,
            embedded_parent_res_id: options.embeddedParentResId || false,
            load_filters: options.loadIrFilters || false,
            toolbar: (!context?.disable_toolbar && options.loadActionMenus) || false,
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
        if (this.env.isSmall) {
            loadViewsOptions.mobile = true;
        }
        if (this.env.debug) {
            loadViewsOptions.debug = true;
        }
        const filteredContext = Object.fromEntries(
            Object.entries(context || {}).filter(
                ([k, v]) => k === "lang" || k.endsWith("_view_ref"),
            ),
        );

        const result = await this.orm
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
}

export const viewService = {
    dependencies: ["orm"],
    async: ["loadViews"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ orm: any }} services
     * @returns {ViewService}
     */
    start(env, services) {
        return new ViewService(env, services);
    },
};

registry.category("services").add("view", viewService);
