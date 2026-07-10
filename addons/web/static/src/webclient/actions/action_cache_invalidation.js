// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_cache_invalidation - Refresh the action stack when an act_window write invalidates server-side action caches */

import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { UPDATE_METHODS } from "@web/services/orm_service";

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
    const onRpcResponse = async (/** @type {any} */ ev) => {
        // ``ev.detail`` may be null (synthetic test fire, or a malformed
        // upstream event); optional-chain so the listener never throws.
        if (!ev.detail?.data?.params) {
            return;
        }
        const { model, method } = ev.detail.data.params;
        if (model === "ir.actions.act_window" && UPDATE_METHODS.includes(method)) {
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "/web/action/load");
            // The client-side breadcrumb display-name cache is stale too;
            // flush it so the recomputation below refetches fresh names.
            am.breadcrumbCache = {};
            const tip = am.controllerStack.at(-1);
            if (!tip) {
                // No active controller — happens in tests that fire
                // ``RPC:RESPONSE`` without mounting a webclient; without this
                // guard, accessing ``tip.config.breadcrumbs`` below throws.
                return;
            }
            const virtualStack = await am._controllersFromState(am.router.current);
            if (am.controllerStack.at(-1) !== tip) {
                // Navigation changed the stack while we awaited: committing
                // ``nextStack`` now would clobber the newer stack. Bail out.
                return;
            }
            const nextStack = [...virtualStack, tip];
            nextStack
                .at(-1)
                .config.breadcrumbs.splice(
                    0,
                    nextStack.at(-1).config.breadcrumbs.length,
                    ...am._getBreadcrumbs(nextStack),
                );
            am.controllerStack = nextStack;
        }
    };
    rpcBus.addEventListener(RpcEvent.RESPONSE, onRpcResponse);
    return () => rpcBus.removeEventListener(RpcEvent.RESPONSE, onRpcResponse);
}
