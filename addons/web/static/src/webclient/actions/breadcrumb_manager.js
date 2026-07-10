// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/breadcrumb_manager - Breadcrumb building, display-name loading, and virtual controller reconstruction for the action service */

/**
 * Breadcrumb management functions for the action service.
 *
 * Handles building breadcrumb items from the controller stack, loading
 * display names for breadcrumb entries, and reconstructing virtual
 * controllers from router state.
 */

import { browser } from "@web/core/browser/browser";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { zip } from "@web/core/utils/collections/arrays";
import { pick } from "@web/core/utils/collections/objects";

const actionRegistry = registry.category("actions");

/** @import { ActionManager } from "./action_service.js" */

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
            get name() {
                return controller.displayName;
            },
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
 * Load breadcrumbs for an array of controllers. Adds display names to
 * controllers that the current user has access to and for which the view
 * (and record) exist. Controllers that correspond to a deleted record or
 * a record/view that the user can't access are removed.
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
            breadcrumbCache[key] = { display_name: displayName };
        }
        if (key in breadcrumbCache) {
            continue;
        }
        toFetch.push(actionInfo);
    }
    if (toFetch.length) {
        const req = rpc("/web/action/load_breadcrumbs", { actions: toFetch });
        for (const [i, info] of toFetch.entries()) {
            const key = JSON.stringify(info);
            breadcrumbCache[key] = req.then(
                (res) => {
                    // Only cache a successful resolution. A per-action ``{error}``
                    // result (e.g. transient ACL race) must NOT be cached, or the
                    // controller is dropped from the breadcrumb/URL for the rest
                    // of the session; evict so a later view re-fetches it.
                    if (res[i] && "display_name" in res[i]) {
                        breadcrumbCache[key] = res[i];
                    } else {
                        delete breadcrumbCache[key];
                    }
                    return res[i];
                },
                (error) => {
                    delete breadcrumbCache[key];
                    throw error;
                },
            );
        }
    }
    const results = await Promise.all(
        controllerKeys.map((ck) => breadcrumbCache[ck.key]),
    );
    const controllersToRemove = [];
    for (const [{ controller }, res] of zip(controllerKeys, results)) {
        if ("display_name" in res) {
            controller.displayName = res.display_name;
        } else {
            controllersToRemove.push(controller);
            if ("error" in res) {
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
        // When loading the state on a form view, we will need to load the action for it,
        // and this will give us the display name of the corresponding multi-record view in
        // the breadcrumb.
        // By marking the last controller as a lazyController, we can in some cases avoid
        // loadBreadcrumbs from doing any network request as the breadcrumbs may only contain
        // the form view and the multi-record view.
        const bcControllers = await loadBreadcrumbs(
            controllers.slice(0, -1),
            am.breadcrumbCache,
        );
        controllers.at(-1).lazy = true;
        return [...bcControllers, controllers.at(-1)];
    }
    return loadBreadcrumbs(controllers, am.breadcrumbCache);
}
