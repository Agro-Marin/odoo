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
 * server-side action caches are stale. Clear them and refresh the current
 * stack's breadcrumbs so the navbar reflects any renamed/removed actions.
 *
 * Extracted from the ActionManager constructor to isolate this cross-cutting
 * concern (it was an anonymous inline closure mixing cache invalidation,
 * router state, and breadcrumb recomputation). Behavior is unchanged; it
 * still reads/commits ``am.controllerStack`` directly, following the
 * established sibling-module convention of taking the manager instance.
 *
 * @param {import("./action_service").ActionManager} am
 * @returns {() => void} disposer that removes the rpcBus listener. There is
 *   currently no ActionManager teardown path in this repo (the webclient's
 *   manager lives for the whole session), but short-lived managers created
 *   through ``makeActionManager`` (e.g. enterprise/web_studio's editor) must
 *   call it on teardown to avoid leaking the listener.
 */
export function installActionCacheInvalidation(am) {
    const onRpcResponse = async (/** @type {any} */ ev) => {
        // ``ev.detail`` itself may be null (synthetic test fires, or a
        // malformed event from an upstream listener). Optional-chain it before
        // reading ``.data`` so the listener never throws.
        if (!ev.detail?.data?.params) {
            return;
        }
        const { model, method } = ev.detail.data.params;
        if (model === "ir.actions.act_window" && UPDATE_METHODS.includes(method)) {
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "/web/action/load");
            // The client-side breadcrumb display-name cache is stale too (and
            // otherwise only grows for the whole session); flush it so the
            // recomputation below refetches fresh names.
            am.breadcrumbCache = {};
            const tip = am.controllerStack.at(-1);
            if (!tip) {
                // No active controller — nothing to refresh. This happens in
                // tests that fire ``RPC:RESPONSE`` without ever mounting a
                // webclient (so ``controllerStack`` is empty); without this
                // guard the access ``tip.config.breadcrumbs`` throws and
                // pollutes the test as an unhandled error.
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
