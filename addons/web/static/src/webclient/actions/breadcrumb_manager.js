// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_manager - Breadcrumb building, display-name loading, and virtual controller reconstruction for the action service */

import { rpc } from "@web/core/network/rpc";
import { zip } from "@web/core/utils/collections/arrays";
import { pick } from "@web/core/utils/collections/objects";

import { resolveClientAction } from "./action_loader.js";
import { actionStorage } from "./action_storage.js";

/** @import { ActionManager } from "./action_service.js" */

/**
 * The home-menu pseudo-controller (web_enterprise's "menu" client action) must
 * never appear in breadcrumbs nor be fetched from the server. It is spelled two
 * ways depending on provenance: ``action.tag === "menu"`` for a live client
 * action loaded by registry key, ``action.id === "menu"`` for a URL-derived
 * virtual controller reconstructed from state. Match both so every breadcrumb
 * discriminator uses one predicate instead of picking one spelling.
 *
 * @param {{ tag?: any, id?: any }} [action]
 * @returns {boolean}
 */
export function isMenuController(action) {
    return action?.tag === "menu" || action?.id === "menu";
}

/**
 * Fetch display names for the given action states in a single
 * ``load_breadcrumbs`` RPC and cache the per-key results.
 *
 * ``retry: 1``: like ``loadAction``, this sits on the refresh/boot path — a
 * transient failure otherwise degrades every breadcrumb of the restored URL.
 *
 * @param {Object[]} toFetch ``{action, model, resId}`` descriptors
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache shared by reference
 */
function fetchBreadcrumbs(toFetch, breadcrumbCache) {
    const req = rpc("/web/action/load_breadcrumbs", { actions: toFetch }, { retry: 1 });
    for (const [i, info] of toFetch.entries()) {
        const key = JSON.stringify(info);
        breadcrumbCache.set(
            key,
            req.then(
                (res) => {
                    if (res[i] && "display_name" in res[i]) {
                        breadcrumbCache.set(key, res[i]);
                    } else {
                        breadcrumbCache.delete(key);
                    }
                    return res[i];
                },
                (error) => {
                    breadcrumbCache.delete(key);
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
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache
 * @returns {Promise<Object[]>} one settled result per key (may be undefined)
 */
function settleBreadcrumbs(controllerKeys, breadcrumbCache) {
    return Promise.all(
        controllerKeys.map((ck) =>
            Promise.resolve(breadcrumbCache.get(ck.key)).catch((error) => ({ error })),
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
        .filter((controller) => !isMenuController(controller.action))
        .map((controller) => ({
            jsId: controller.jsId,
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
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache shared by reference
 * @returns {Promise<Object[]>} new array of displayable controllers with display names
 */
async function loadBreadcrumbs(controllers, breadcrumbCache) {
    const toFetch = [];
    const controllerKeys = [];
    for (const controller of controllers) {
        const { action, state, displayName } = controller;
        if (
            isMenuController(action) ||
            (action.type === "ir.actions.client" && !displayName)
        ) {
            continue;
        }
        const actionInfo = pick(state, "action", "model", "resId");
        const key = JSON.stringify(actionInfo);
        controllerKeys.push({ controller, key });
        if (displayName) {
            breadcrumbCache.set(key, { display_name: displayName });
        }
        if (breadcrumbCache.has(key)) {
            breadcrumbCache.touch(key);
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
 * @param {import("./breadcrumb_cache.js").BreadcrumbCache} breadcrumbCache shared by reference
 * @returns {Promise<void>}
 */
export async function refreshBreadcrumbDisplayNames(controllers, breadcrumbCache) {
    const toFetch = [];
    const controllerKeys = [];
    const seen = new Set();
    for (const controller of controllers) {
        const { action, state } = controller;
        if (!state || isMenuController(action) || action.type === "ir.actions.client") {
            continue;
        }
        const actionInfo = pick(state, "action", "model", "resId");
        const key = JSON.stringify(actionInfo);
        controllerKeys.push({ controller, key });
        if (!breadcrumbCache.has(key) && !seen.has(key)) {
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
 * Reads the restore cache (``actionStorage``) and the singleton client-action
 * registry (via ``resolveClientAction``) directly; only the per-instance state
 * (``router.stateToUrl``, ``_makeController``, ``breadcrumbCache``) comes
 * off the action manager.
 *
 * @param {Object} state the router state
 * @param {ActionManager} am
 * @returns {Promise<Object[]>} array of virtual controllers
 */
export async function controllersFromState(state, am) {
    const currentState = actionStorage.getCurrentState();
    if (am.router.stateToUrl(currentState) === am.router.stateToUrl(state)) {
        state = currentState;
    }
    if (!state?.actionStack?.length) {
        return [];
    }
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

                const [actionRequestKey, clientAction] = resolveClientAction(
                    actionState.action,
                );
                if (actionRequestKey && clientAction) {
                    if (state.actionStack[index + 1]?.action === actionState.action) {
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
        const bcControllers = await loadBreadcrumbs(
            controllers.slice(0, -1),
            am.breadcrumbCache,
        );
        controllers.at(-1).lazy = true;
        return [...bcControllers, controllers.at(-1)];
    }
    return loadBreadcrumbs(controllers, am.breadcrumbCache);
}
