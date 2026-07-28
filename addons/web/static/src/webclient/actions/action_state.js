// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_state - URL state serialization/deserialization for the action service (router integration) */

import { markup } from "@odoo/owl";
import { PATH_KEYS } from "@web/core/browser/router";
import { omit, pick, shallowEqual } from "@web/core/utils/collections/objects";
import { user } from "@web/services/user";

import { parseActiveIds } from "./action_constants.js";
import { resolveClientAction } from "./action_loader.js";
import { actionStorage } from "./action_storage.js";

/**
 * Serialize a controller stack into a URL-pushable state object.
 *
 * Produces an `actionStack` array (one entry per controller) plus
 * top-level keys for the last controller's state so that the router
 * can reconstruct the breadcrumb on page load.
 *
 * @param {Object[]} controllerStack - array of controller objects
 * @returns {Object} state suitable for `router.pushState`
 */
export function makeActionState(controllerStack) {
    const actions = controllerStack.map((controller) => {
        const { action, props, displayName } = controller;
        const actionState = { displayName };
        if (action.path || action.id) {
            actionState.action = action.path || action.id;
        } else if (action.type === "ir.actions.client") {
            actionState.action = action.tag;
        } else if (action.type === "ir.actions.act_window") {
            actionState.model = props.resModel;
        }
        if (action.type === "ir.actions.act_window") {
            actionState.view_type = props.type;
            if (props.type === "form" && action.res_model !== "res.config.settings") {
                actionState.resId = controller.currentState.resId || "new";
            }
        }
        if (action.type === "ir.actions.client" && controller.currentState?.resId) {
            actionState.resId = controller.currentState.resId;
        }

        if (controller.currentState?.active_id != null) {
            actionState.active_id = controller.currentState.active_id;
        }
        Object.assign(actionState, omit(controller.currentState || {}, ...PATH_KEYS));
        return actionState;
    });
    const newState = {
        actionStack: actions,
    };
    const stateKeys = [...PATH_KEYS];
    const { action, props, currentState } = controllerStack.at(-1);
    if (props.type !== "form" && props.type !== action.views?.[0]?.[1]) {
        stateKeys.push("view_type");
    }
    if (currentState) {
        stateKeys.push(...Object.keys(omit(currentState, ...PATH_KEYS)));
    }
    return Object.assign(
        newState,
        pick(newState.actionStack.at(-1), .../** @type {any} */ (stateKeys)),
    );
}

/**
 * Reconstruct an action request and options from a URL state object.
 *
 * Restores client actions from the registry, window actions from session
 * storage, and handles recursive actionStack unwinding for invalid states.
 * Pure function — all external dependencies are module-level imports.
 *
 * When the leaf entry cannot be resolved the tail of ``actionStack`` is popped
 * and the parse retried; ``options.poppedLeaves`` reports HOW MANY entries were
 * dropped. It is deliberately a COUNT and not a position: the caller applies it
 * to the CONTROLLER stack rebuilt by ``controllersFromState``, which is shorter
 * than ``actionStack`` whenever a record turned out to be deleted or
 * inaccessible. An absolute index into the URL stack silently means a different
 * entry once that happens — it kept the resolved action's own controller as its
 * own breadcrumb parent.
 *
 * @param {Object} state - the URL state to parse
 * @returns {{ actionRequest: Object, options: Object } | null}
 */
export function getActionParams(state) {
    /**
     * @type {{
     *   additionalContext?: Object,
     *   viewType?: string,
     *   poppedLeaves?: number,
     *   props?: { resId?: any, globalState?: any },
     * }}
     */
    const options = {};
    let actionRequest = null;
    const lastAction = actionStorage.getCurrentAction();
    delete lastAction.context?.allowed_company_ids;
    if (lastAction.help) {
        lastAction.help = markup(lastAction.help);
    }
    if (state.action) {
        const context = {};
        if (state.active_id) {
            context.active_id = state.active_id;
        }
        if (state.active_ids) {
            context.active_ids = parseActiveIds(state.active_ids);
        } else if (state.active_id) {
            context.active_ids = [state.active_id];
        }
        const [actionRequestKey, clientAction] = resolveClientAction(state.action);
        if (actionRequestKey && clientAction) {
            actionRequest = /** @type {any} */ ({
                context,
                params: state,
                tag: actionRequestKey,
                type: "ir.actions.client",
            });
            if (/** @type {any} */ (clientAction).path) {
                actionRequest.path = /** @type {any} */ (clientAction).path;
            }
        } else {
            Object.assign(options, {
                additionalContext: context,
                viewType: state.resId ? "form" : state.view_type,
            });
            if (
                [lastAction.id, lastAction.path, lastAction.xml_id]
                    .filter(Boolean)
                    .includes(state.action) &&
                (!lastAction.context?.active_id ||
                    lastAction.context?.active_id === context.active_id) &&
                (!lastAction.context?.active_ids ||
                    shallowEqual(lastAction.context?.active_ids, context.active_ids)) &&
                !lastAction.embedded_action_ids?.length
            ) {
                actionRequest = lastAction;
            } else {
                actionRequest = state.action;
            }
        }
        if (state.resId && state.resId !== "new") {
            options.props = { resId: state.resId };
        }
    } else if (state.model) {
        if (state.resId || state.view_type === "form") {
            if (!lastAction.id && lastAction.res_model === state.model) {
                actionRequest = lastAction;
                options.props = {
                    resId: state.resId === "new" ? undefined : state.resId,
                };
                if (state.view_id) {
                    actionRequest.views = [[state.view_id, "form"]];
                }
                options.viewType = "form";
            } else {
                actionRequest = {
                    res_model: state.model,
                    res_id: state.resId === "new" ? undefined : state.resId,
                    type: "ir.actions.act_window",
                    views: [[state.view_id ? state.view_id : false, "form"]],
                };
            }
        } else {
            if (lastAction.res_model === state.model) {
                actionRequest = lastAction;
                options.viewType = state.view_type;
            }
        }
    }
    // One rule for every shape of request the branches above can resolve.
    // ``globalState`` (the serialized search model) is hidden from the URL but
    // rides along in the history entry, so Back onto a ``/odoo/m-<model>``
    // route must restore the user's facets exactly as Back onto an
    // ``/odoo/action-<id>`` one does; restoring it only in the action branch
    // silently emptied the search bar for model-based routes.
    if (actionRequest && state.globalState) {
        options.props = { ...options.props, globalState: state.globalState };
    }
    if (!actionRequest) {
        const { actionStack } = state;
        if (actionStack?.length > 1) {
            const nextState = { actionStack: actionStack.slice(0, -1) };
            Object.assign(nextState, nextState.actionStack.at(-1));
            const params = getActionParams(nextState);
            if (!params) {
                return null;
            }
            if (params.options) {
                params.options.poppedLeaves = (params.options.poppedLeaves || 0) + 1;
            }
            return params;
        }
        actionRequest = user.homeActionId;
    }
    return actionRequest ? { actionRequest, options } : null;
}
