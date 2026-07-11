// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_button_executor - Executes action buttons (type=object/action/special) with RPC, context filtering, and UI blocking */

/**
 * Extracted action-button execution logic; takes an {@link ActionManager}
 * instance and accesses the service's methods/state through it.
 */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { omit } from "@web/core/utils/collections/objects";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { user } from "@web/services/user";

import { CTX_KEY_REGEX, EMBEDDED_ACTIONS_CTX_KEYS } from "./action_constants.js";

/** @typedef {Object} DoActionButtonParams */
/** @import { ActionManager } from "./action_service.js" */

export class InvalidButtonParamsError extends Error {}

/**
 * Build the positional ``args`` for a ``call_button`` RPC: the record id(s)
 * followed by any explicit ``args`` arch attribute (a Python-literal list).
 *
 * @param {DoActionButtonParams} params
 * @returns {any[]}
 * @throws {InvalidButtonParamsError} if ``args`` is unparseable or not a list
 */
export function buildCallButtonArgs(params) {
    let args = params.resId ? [[params.resId]] : [params.resIds];
    if (params.args) {
        let additionalArgs;
        try {
            // arch `args` is a Python-literal list (e.g. args="[1, 'foo']");
            // evaluateExpr parses Python literals natively so quoting round-trips.
            additionalArgs = evaluateExpr(params.args);
        } catch (error) {
            throw new InvalidButtonParamsError(
                `Could not evaluate the "args" attribute of button "${params.name}": ${params.args}`,
                { cause: error },
            );
        }
        if (!Array.isArray(additionalArgs)) {
            throw new InvalidButtonParamsError(
                `The "args" attribute of button "${params.name}" must evaluate to a list, got: ${params.args}`,
            );
        }
        args = [...args, ...additionalArgs];
    }
    return args;
}

/**
 * Strip context keys that must not leak from the originating action into the
 * destination action's context — wrong ``default_*`` / ``search_default_*``
 * values, or a ``group_by`` the destination view can't satisfy. The stripped
 * set is defined by {@link CTX_KEY_REGEX}.
 *
 * @param {Object} [context]
 * @returns {Object} a new context with the action-specific keys removed
 */
export function filterActionContext(context) {
    const filtered = {};
    for (const [key, value] of Object.entries(context || {})) {
        if (key.match(CTX_KEY_REGEX) === null) {
            filtered[key] = value;
        }
    }
    return filtered;
}

/**
 * Execute an action button (type="object", type="action", or special).
 *
 * Handles RPC calls, embedded-action recursion, context filtering,
 * UI blocking, and effect triggering.
 *
 * @param {ActionManager} am
 * @param {DoActionButtonParams} params
 * @param {Object} [options={}]
 * @param {boolean} [options.isEmbeddedAction] set to true if the action
 *   request is an embedded action (avoids infinite recursion).
 * @param {boolean} [options.newWindow] set to true to open in a new tab.
 * @returns {Promise<void>}
 */
export async function executeActionButton(
    am,
    params,
    { isEmbeddedAction, newWindow } = {},
) {
    if (!params.name && !params.special) {
        return;
    }
    let action;
    if (!isEmbeddedAction && params.context) {
        // `params.context` frequently aliases a view-owned context object:
        // strip the embedded-action keys on a copy so the deletion cannot
        // leak back into the originating view's state.
        params = {
            ...params,
            context: omit(params.context, ...EMBEDDED_ACTIONS_CTX_KEYS),
        };
    }
    const context = makeContext([params.context, params.buttonContext]);
    const blockUi = exprToBoolean(params["block-ui"]);
    if (blockUi) {
        am.env.services.ui.block();
    }
    // The whole block runs in try/finally so the `block-ui` overlay is always
    // released, whatever exit path is taken (rejected RPC, invalid-args throw,
    // embedded-action early return). `effect` is declared here and triggered
    // after the finally so the spinner is removed before the effect plays.
    let effect;
    try {
        if (params.special) {
            action = {
                type: "ir.actions.act_window_close",
                infos: { special: true },
            };
        } else if (params.type === "object") {
            // call a Python Object method, which may return an action to execute
            const args = buildCallButtonArgs(params);
            const callProm = rpc(
                `/web/dataset/call_button/${params.resModel}/${params.name}`,
                {
                    args,
                    kwargs: { context },
                    method: params.name,
                    model: params.resModel,
                },
            );
            // am.keepLast rejects with a SupersededError if a newer task
            // supersedes this one; the `finally` still releases the block-ui
            // overlay and the error service swallows the rejection.
            action = await am.keepLast.add(callProm);
            action =
                action && typeof action === "object"
                    ? action
                    : { type: "ir.actions.act_window_close" };
            if (action.help) {
                action.help = markup(action.help);
            }
        } else if (params.type === "action") {
            // execute a given action, so load it first
            context.active_id = params.resId ?? null;
            context.active_ids = params.resIds;
            context.active_model = params.resModel;
            action = await am.keepLast.add(am._loadAction(params.name, context));
        } else {
            throw new InvalidButtonParamsError(
                "Missing type for doActionButton request",
            );
        }
        if (!isEmbeddedAction && action.embedded_action_ids?.length) {
            const embeddedActionsKey = `${action.id}+${params.resId || ""}`;
            const embeddedActionsOrder =
                user.settings.embedded_actions_config_ids?.[embeddedActionsKey]
                    ?.embedded_actions_order;
            const embeddedActionId = embeddedActionsOrder?.[0];
            const embeddedAction = action.embedded_action_ids?.find(
                (embeddedAction) => embeddedAction.id === embeddedActionId,
            );
            if (embeddedAction) {
                const embeddedActions = [
                    ...action.embedded_action_ids,
                    {
                        id: false,
                        name: action.name,
                        parent_action_id: action.id,
                        parent_res_model: action.res_model,
                        action_id: action.id,
                        user_id: false,
                        context: {},
                    },
                ];
                const embeddedContext = {
                    ...action.context,
                    ...(embeddedAction.context
                        ? makeContext([embeddedAction.context])
                        : {}),
                    active_id: params.resId,
                    active_model: params.resModel,
                    current_embedded_action_id: embeddedActionId,
                    parent_action_embedded_actions: embeddedActions,
                    parent_action_id: action.id,
                };
                await am.doActionButton(
                    {
                        name:
                            embeddedAction.python_method ||
                            embeddedAction.action_id[0] ||
                            embeddedAction.action_id,
                        resId: params.resId,
                        context: embeddedContext,
                        type: embeddedAction.python_method ? "object" : "action",
                        resModel: embeddedAction.parent_res_model,
                        viewType: embeddedAction.default_view_mode,
                    },
                    { isEmbeddedAction: true },
                );
                return;
            }
        }
        // filter out context keys specific to the current action (see filterActionContext)
        const currentCtx = filterActionContext(params.context);
        const activeCtx = { active_model: params.resModel };
        if (params.resId) {
            activeCtx.active_id = params.resId;
            activeCtx.active_ids = [params.resId];
        }
        action.context = makeContext([
            currentCtx,
            params.buttonContext,
            activeCtx,
            action.context,
        ]);
        // in case an effect is returned from python and there is already an effect
        // attribute on the button, the priority is given to the button attribute
        effect = params.effect ? evaluateExpr(params.effect) : action.effect;
        const { onClose, stackPosition, viewType } = params;
        // doAction rejects with a SupersededError when this dispatch is
        // superseded before its controller mounts (its currentActionProm is
        // rejected in ControllerComponent.onWillDestroy); the `finally` still
        // releases the block-ui overlay and the error service swallows it.
        await am.doAction(action, {
            newWindow,
            onClose,
            stackPosition,
            viewType,
        });
        if (params.close) {
            await am._executeCloseAction();
        }
    } finally {
        if (blockUi) {
            am.env.services.ui.unblock();
        }
    }
    if (effect) {
        am.env.services.effect.add(effect);
    }
}
