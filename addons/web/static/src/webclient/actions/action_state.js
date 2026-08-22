// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { PATH_KEYS } from "@web/core/browser/router";
import { user } from "@web/core/user";
import { omit, pick, shallowEqual } from "@web/core/utils/collections/objects";

import { parseActiveIds } from "./action_constants.js";
import { resolveClientAction } from "./action_loader.js";
import { actionStorage } from "./action_storage.js";

/** @import { ActionOptions, ActionRequest, Context, Controller } from "./action_service.js" */

/**
 * @param {Controller[]} controllerStack
 * @returns {Record<string, any>}
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
    const { action, props, currentState } = /** @type {Controller} */ (
        controllerStack.at(-1)
    );
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
 * @param {Record<string, any>} state
 * @returns {Context}
 */
function buildActiveContext(state) {
    /** @type {Context} */
    const context = {};
    if (state.active_id) {
        context.active_id = state.active_id;
    }
    if (state.active_ids) {
        context.active_ids = parseActiveIds(state.active_ids);
    } else if (state.active_id) {
        context.active_ids = [state.active_id];
    }
    return context;
}

/**
 * Whether the action kept in session storage is the one the url names, so it can
 * be replayed with its domain and context instead of re-loaded by key. Embedded
 * actions are excluded: the stored copy carries the parent's own view, not the
 * embedded one the url is asking for.
 *
 * @param {Record<string, any>} lastAction
 * @param {Record<string, any>} state
 * @param {Context} context
 * @returns {boolean}
 */
function storedActionAnswersTo(lastAction, state, context) {
    return (
        [lastAction.id, lastAction.path, lastAction.xml_id]
            .filter(Boolean)
            .includes(state.action) &&
        (!lastAction.context?.active_id ||
            lastAction.context?.active_id === context.active_id) &&
        (!lastAction.context?.active_ids ||
            shallowEqual(lastAction.context?.active_ids, context.active_ids)) &&
        !lastAction.embedded_action_ids?.length
    );
}

/**
 * @param {Record<string, any>} state
 * @param {Record<string, any>} lastAction
 * @param {Record<string, any>} options mutated in place
 * @returns {ActionRequest | null}
 */
function resolveActionFromKey(state, lastAction, options) {
    const context = buildActiveContext(state);
    const [actionRequestKey, clientAction] = resolveClientAction(state.action);
    let actionRequest;
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
        actionRequest = storedActionAnswersTo(lastAction, state, context)
            ? lastAction
            : state.action;
    }
    if (state.resId && state.resId !== "new") {
        options.props = { resId: state.resId };
    }
    return actionRequest;
}

/**
 * A url naming a model rather than an action can only be replayed exactly when
 * the stored action is for that same model. Failing that, a record still opens
 * as a bare form -- the id identifies it -- but a multi-record view does not:
 * rebuilding one without the original domain would show a wider set than the
 * url ever meant.
 *
 * @param {Record<string, any>} state
 * @param {Record<string, any>} lastAction
 * @param {Record<string, any>} options mutated in place
 * @returns {ActionRequest | null}
 */
function resolveActionFromModel(state, lastAction, options) {
    if (!state.resId && state.view_type !== "form") {
        if (lastAction.res_model !== state.model) {
            return null;
        }
        options.viewType = state.view_type;
        return lastAction;
    }
    const resId = state.resId === "new" ? undefined : state.resId;
    if (!lastAction.id && lastAction.res_model === state.model) {
        options.props = { resId };
        options.viewType = "form";
        if (state.view_id) {
            lastAction.views = [[state.view_id, "form"]];
        }
        return lastAction;
    }
    return /** @type {any} */ ({
        res_model: state.model,
        res_id: resId,
        type: "ir.actions.act_window",
        views: [[state.view_id ? state.view_id : false, "form"]],
    });
}

/**
 * @param {Record<string, any>} state
 * @returns {{ actionRequest: ActionRequest, options: ActionOptions } | null}
 */
export function getActionParams(state) {
    /**
     * @type {{
     * additionalContext?: Object,
     * viewType?: string,
     * poppedLeaves?: number,
     * props?: { resId?: any, globalState?: any },
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
        actionRequest = resolveActionFromKey(state, lastAction, options);
    } else if (state.model) {
        actionRequest = resolveActionFromModel(state, lastAction, options);
    }
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
            params.options.poppedLeaves = (params.options.poppedLeaves || 0) + 1;
            return params;
        }
        actionRequest = user.homeActionId;
    }
    return actionRequest ? { actionRequest, options } : null;
}
