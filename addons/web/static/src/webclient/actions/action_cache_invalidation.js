// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_cache_invalidation - Refresh the action stack when an act_window write invalidates server-side action caches */

import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { onModelMutation } from "@web/services/orm_service";

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
    // Model matching is a prefix test, so a predicate rather than a list.
    // A write REFUSED by the server (RPCError) is filtered out by
    // ``onModelMutation``: nothing changed, so flushing the disk cache and
    // refetching breadcrumbs would be pure waste right after the user already
    // got an error dialog. A write whose response was merely lost still fires.
    return onModelMutation(
        (model) => model.startsWith("ir.actions."),
        async ({ model }) => {
            // Any action-type write (server/report/client/act_url/act_window)
            // stales the /web/action/load disk cache, which has no
            // background revalidation — a stale descriptor was served from
            // IndexedDB on every execution, surviving page reloads, until an
            // unrelated act_window write happened to flush it. Clear on all
            // ir.actions.* writes.
            rpcBus.trigger(RpcEvent.CLEAR_CACHES, "/web/action/load");
            // The breadcrumb display-name refresh below only concerns
            // act_window records (the only type shown in breadcrumbs); other
            // action types just need the descriptor cache cleared above.
            if (model !== "ir.actions.act_window") {
                return;
            }
            // The client-side breadcrumb display-name cache is stale too;
            // flush it so the recomputation below refetches fresh names.
            //
            // A fresh instance, NOT clear(): fetchBreadcrumbs captures the
            // cache by reference and fills it from a `.then`, so a
            // load_breadcrumbs issued before this write committed would
            // repopulate a cleared cache with pre-write names. Replacing
            // orphans that in-flight result.
            am.breadcrumbCache = new BreadcrumbCache();
            const stack = am.controllerStack;
            const tip = stack.at(-1);
            if (!tip) {
                // No active controller — happens in tests that fire
                // ``RPC:RESPONSE`` without mounting a webclient; without this
                // guard, accessing ``tip.config.breadcrumbs`` below throws.
                return;
            }
            // Refresh in place: recompute display names into the existing
            // controllers instead of swapping in URL-derived virtual ones,
            // which would lose their live state (exportedState, cached view
            // controllers) and force full doAction re-execution on restore.
            await refreshBreadcrumbDisplayNames(stack, am.breadcrumbCache);
            if (am.controllerStack.at(-1) !== tip) {
                // Navigation changed the stack while we awaited: the new tip's
                // breadcrumbs were built from fresh caches already. Bail out.
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
