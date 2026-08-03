// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_cache_invalidation */

import { RpcEvent } from "@web/core/events";
import { onModelMutation } from "@web/core/network/model_mutation";
import { rpcBus } from "@web/core/network/rpc";

import { BreadcrumbCache } from "./breadcrumb_cache.js";
import { refreshBreadcrumbDisplayNames } from "./breadcrumb_manager.js";

/**
 * Models whose mutation must bust the disk-cached `/web/action/load`. The route
 * caches the action dict, which `ir.actions.actions._get_action_dict` expands to
 * inline the action's `embedded_action_ids` (`ir.embedded.actions`). So creating,
 * writing or deleting an embedded action changes what a cached action payload
 * *should* contain -- yet the model name is `ir.embedded.actions`, not
 * `ir.actions.*`, so a prefix-only match silently leaves the cache (and the
 * embedded-action tabs built from it) stale after navigating back through it.
 *
 * @param {string} model
 * @returns {boolean}
 */
function mutatesActionLoadPayload(model) {
    return model.startsWith("ir.actions.") || model === "ir.embedded.actions";
}

/**
 * @param {import("./action_service").ActionManager} am
 * @returns {() => void}
 */
export function installActionCacheInvalidation(am) {
    return onModelMutation(mutatesActionLoadPayload, async ({ model }) => {
        rpcBus.trigger(RpcEvent.CLEAR_CACHES, "/web/action/load");
        if (model !== "ir.actions.act_window") {
            return;
        }
        am.breadcrumbCache = new BreadcrumbCache();
        const stack = am.controllerStack;
        const tip = stack.at(-1);
        if (!tip?.config?.breadcrumbs) {
            return;
        }
        await refreshBreadcrumbDisplayNames(stack, am.breadcrumbCache);
        if (am.controllerStack.at(-1) !== tip) {
            return;
        }
        tip.config.breadcrumbs.splice(
            0,
            tip.config.breadcrumbs.length,
            ...am._getBreadcrumbs(stack),
        );
    });
}
