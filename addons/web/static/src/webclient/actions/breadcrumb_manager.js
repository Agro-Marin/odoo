// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_manager - Breadcrumb building, display-name loading, and virtual controller reconstruction for the action service */

import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { zip } from "@web/core/utils/collections/arrays";
import { pick } from "@web/core/utils/collections/objects";

const actionRegistry = registry.category("actions");

/**
 * Maximum number of entries kept in the breadcrumb display-name cache. The
 * cache is otherwise only flushed on ``ir.actions.act_window`` writes, so in
 * a long-lived session it would grow one entry per unique
 * ``{action, model, resId}`` visited, unboundedly.
 */
const BREADCRUMB_CACHE_LIMIT = 200;

/** @import { ActionManager } from "./action_service.js" */

/**
 * Write an entry into the breadcrumb cache, evicting the least recently used
 * one when the cache is full. Plain objects preserve string-key insertion
 * order and hits are re-inserted (see the lookup sites), so the first key is
 * always the coldest.
 *
 * @param {Object} breadcrumbCache
 * @param {string} key
 * @param {any} value
 */
function setBreadcrumbCacheEntry(breadcrumbCache, key, value) {
    if (!(key in breadcrumbCache)) {
        const keys = Object.keys(breadcrumbCache);
        if (keys.length >= BREADCRUMB_CACHE_LIMIT) {
            delete breadcrumbCache[keys[0]];
        }
    }
    breadcrumbCache[key] = value;
}

/**
 * Fetch display names for the given action states in a single
 * ``load_breadcrumbs`` RPC and cache the per-key results.
 *
 * ``retry: 1``: like ``loadAction``, this sits on the refresh/boot path — a
 * transient failure otherwise degrades every breadcrumb of the restored URL.
 *
 * @param {Object[]} toFetch ``{action, model, resId}`` descriptors
 * @param {Object} breadcrumbCache mutable cache object (shared by reference)
 */
function fetchBreadcrumbs(toFetch, breadcrumbCache) {
    const req = rpc("/web/action/load_breadcrumbs", { actions: toFetch }, { retry: 1 });
    for (const [i, info] of toFetch.entries()) {
        const key = JSON.stringify(info);
        setBreadcrumbCacheEntry(
            breadcrumbCache,
            key,
            req.then(
                (res) => {
                    // Only cache a successful resolution: caching a per-action
                    // {error} (e.g. transient ACL race) would drop the controller
                    // for the rest of the session, so evict it instead.
                    if (res[i] && "display_name" in res[i]) {
                        setBreadcrumbCacheEntry(breadcrumbCache, key, res[i]);
                    } else {
                        delete breadcrumbCache[key];
                    }
                    return res[i];
                },
                (error) => {
                    delete breadcrumbCache[key];
                    throw error;
                },
            ),
        );
    }
}

/**
 * Await the cached results for the given keys, degrading per-entry: a
 * rejected fetch resolves to ``{error}`` instead of rejecting the batch, so
 * one failed RPC never propagates a wholesale rejection to the caller.
 *
 * @param {{controller: Object, key: string}[]} controllerKeys
 * @param {Object} breadcrumbCache
 * @returns {Promise<Object[]>} one settled result per key (may be undefined)
 */
function settleBreadcrumbs(controllerKeys, breadcrumbCache) {
    return Promise.all(
        controllerKeys.map((ck) =>
            Promise.resolve(breadcrumbCache[ck.key]).catch((error) => ({ error })),
        ),
    );
}

/**
 * Given a controller stack, return the list of breadcrumb items.
 *
 * @param {Object[]} stack the controller stack
 * @param {ActionManager} am
 * @returns {Object[]} breadcrumb items
 */
export function buildBreadcrumbs(stack, am) {
    return stack
        .filter((controller) => controller.action.tag !== "menu")
        .map((controller) => ({
            jsId: controller.jsId,
            // Plain slot (not a getter): the items live in a reactive array,
            // so a later `config.setDisplayName` writes the new name through
            // it and notifies exactly the subscribers that read this crumb.
            name: controller.displayName,
            get isFormView() {
                return controller.props?.type === "form";
            },
            get url() {
                return am.router.stateToUrl(controller.state);
            },
            onSelected() {
                am.restore(controller.jsId);
            },
        }));
}

/**
 * Load breadcrumbs for controllers with view/record access, adding display
 * names; controllers for deleted/inaccessible records are removed.
 *
 * @param {Object[]} controllers controllers whose breadcrumbs should be loaded
 * @param {Object} breadcrumbCache mutable cache object (shared by reference)
 * @returns {Promise<Object[]>} new array of displayable controllers with display names
 */
async function loadBreadcrumbs(controllers, breadcrumbCache) {
    const toFetch = [];
    // Track which controllers have associated keys (non-skipped ones)
    const controllerKeys = [];
    for (const controller of controllers) {
        const { action, state, displayName } = controller;
        if (
            action.id === "menu" ||
            (action.type === "ir.actions.client" && !displayName)
        ) {
            continue;
        }
        const actionInfo = pick(state, "action", "model", "resId");
        const key = JSON.stringify(actionInfo);
        controllerKeys.push({ controller, key });
        if (displayName) {
            setBreadcrumbCacheEntry(breadcrumbCache, key, {
                display_name: displayName,
            });
        }
        if (key in breadcrumbCache) {
            // LRU touch: re-insert the hit so it moves to the warm end.
            const hit = breadcrumbCache[key];
            delete breadcrumbCache[key];
            breadcrumbCache[key] = hit;
            continue;
        }
        toFetch.push(actionInfo);
    }
    if (toFetch.length) {
        fetchBreadcrumbs(toFetch, breadcrumbCache);
    }
    const results = await settleBreadcrumbs(controllerKeys, breadcrumbCache);
    const controllersToRemove = [];
    for (const [{ controller }, res] of zip(controllerKeys, results)) {
        if (res && "display_name" in res) {
            controller.displayName = res.display_name;
        } else {
            controllersToRemove.push(controller);
            if (res && "error" in res) {
                console.warn(
                    "The following element was removed from the breadcrumb and from the url.\n",
                    controller.state,
                    "\nThis could be because the action wasn't found or because the user doesn't have the right to access to the record, the original error is :\n",
                    res.error,
                );
            }
        }
    }
    return controllers.filter((c) => !controllersToRemove.includes(c));
}

/**
 * Re-fetch fresh display names for the given (live, non-virtual) controllers
 * into ``controller.displayName`` after a server-side action change.
 *
 * Unlike {@link loadBreadcrumbs}, existing display names are not trusted as
 * cache seeds (they are exactly what may be stale) and controllers are never
 * dropped: on a failed or errored fetch the current name is kept, since the
 * controllers hold live state (exported view state, cached sub-controllers)
 * that must survive a background refresh.
 *
 * @param {Object[]} controllers
 * @param {Object} breadcrumbCache mutable cache object (shared by reference)
 * @returns {Promise<void>}
 */
export async function refreshBreadcrumbDisplayNames(controllers, breadcrumbCache) {
    const toFetch = [];
    const controllerKeys = [];
    const seen = new Set();
    for (const controller of controllers) {
        const { action, state } = controller;
        if (!state || action.id === "menu" || action.type === "ir.actions.client") {
            // Client action names come from the registry, not the server.
            continue;
        }
        const actionInfo = pick(state, "action", "model", "resId");
        const key = JSON.stringify(actionInfo);
        controllerKeys.push({ controller, key });
        if (!(key in breadcrumbCache) && !seen.has(key)) {
            seen.add(key);
            toFetch.push(actionInfo);
        }
    }
    if (toFetch.length) {
        fetchBreadcrumbs(toFetch, breadcrumbCache);
    }
    const results = await settleBreadcrumbs(controllerKeys, breadcrumbCache);
    for (const [{ controller }, res] of zip(controllerKeys, results)) {
        if (res && "display_name" in res) {
            controller.displayName = res.display_name;
        }
    }
}

/**
 * Create an array of virtual controllers based on the given router state.
 *
 * Reads ``browser.sessionStorage`` and the singleton client-action
 * ``registry.category("actions")`` directly; only the per-instance state
 * (``router.stateToUrl``, ``_makeController``, ``breadcrumbCache``) comes
 * off the action manager.
 *
 * @param {Object} state the router state
 * @param {ActionManager} am
 * @returns {Promise<Object[]>} array of virtual controllers
 */
export async function controllersFromState(state, am) {
    const currentState = JSON.parse(
        browser.sessionStorage.getItem("current_state") || "{}",
    );
    if (am.router.stateToUrl(currentState) === am.router.stateToUrl(state)) {
        state = currentState;
    }
    if (!state?.actionStack?.length) {
        return [];
    }
    // The last controller will be created by doAction and won't be virtual
    const controllers = state.actionStack
        .slice(0, -1)
        .map((actionState, index) => {
            const controller = am._makeController({
                displayName: actionState.displayName,
                virtual: true,
                action: {},
                props: {},
                state: {
                    ...actionState,
                    actionStack: state.actionStack.slice(0, index + 1),
                },
                currentState: {},
            });
            if (actionState.action) {
                controller.action.id = actionState.action;

                const [actionRequestKey, clientAction] = actionRegistry.contains(
                    actionState.action,
                )
                    ? [actionState.action, actionRegistry.get(actionState.action)]
                    : (actionRegistry
                          .getEntries()
                          .find((a) => a[1].path === actionState.action) ?? []);
                if (actionRequestKey && clientAction) {
                    if (state.actionStack[index + 1]?.action === actionState.action) {
                        // client actions don't have multi-record views, so we can't go further to the next controller
                        return;
                    }
                    controller.action.tag = actionRequestKey;
                    controller.action.type = "ir.actions.client";
                    controller.displayName = clientAction.displayName?.toString();
                }
                if (actionState.active_id) {
                    controller.action.context = {
                        active_id: actionState.active_id,
                    };
                    controller.currentState.active_id = actionState.active_id;
                }
            }
            if (actionState.model) {
                controller.action.type = "ir.actions.act_window";
                controller.props.resModel = actionState.model;
            }
            if (actionState.resId) {
                controller.action.type ||= "ir.actions.act_window";
                controller.props.resId = actionState.resId;
                controller.currentState.resId = actionState.resId;
                controller.props.type = "form";
            }
            return controller;
        })
        .filter(Boolean);

    if (
        state.action &&
        state.resId &&
        controllers.at(-1)?.action?.id === state.action
    ) {
        // Loading state on a form view needs the action loaded too, to get the
        // multi-record view's display name for the breadcrumb. Marking the last
        // controller lazy lets loadBreadcrumbs sometimes skip that network call.
        const bcControllers = await loadBreadcrumbs(
            controllers.slice(0, -1),
            am.breadcrumbCache,
        );
        controllers.at(-1).lazy = true;
        return [...bcControllers, controllers.at(-1)];
    }
    return loadBreadcrumbs(controllers, am.breadcrumbCache);
}
