// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_cache_invalidation - Refresh the action stack when an act_window write invalidates server-side action caches */

import { RpcEvent } from "@web/core/events";
import { onModelMutation } from "@web/core/network/model_mutation";
import { rpcBus } from "@web/core/network/rpc";

import { BreadcrumbCache } from "./breadcrumb_cache.js";
import { refreshBreadcrumbDisplayNames } from "./breadcrumb_manager.js";

/**
 * Install the RPC cache-invalidation listener for an ActionManager.
 *
 * When a mutating RPC (write/unlink/...) targets ``ir.actions.act_window`` the
 * server-side action caches are stale; clear them and refresh the current
 * stack's breadcrumbs so the navbar reflects any renamed/removed actions.
 *
 * @param {import("./action_service").ActionManager} am
 * @returns {() => void} disposer that removes the rpcBus listener. The
 *   webclient's own manager never calls it (it lives for the session), but
 *   short-lived managers from ``makeActionManager`` (e.g. web_studio's
 *   editor) must call it on teardown to avoid leaking the listener.
 */
export function installActionCacheInvalidation(am) {
    return onModelMutation(
        (model) => model.startsWith("ir.actions."),
        async ({ model }) => {
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "/web/action/load");
            if (model !== "ir.actions.act_window") {
                return;
            }
            am.breadcrumbCache = new BreadcrumbCache();
            const stack = am.controllerStack;
            const tip = stack.at(-1);
            if (!tip) {
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
        },
    );
}
