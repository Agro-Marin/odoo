// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_button_executor - Executes action buttons (type=object/action/special) with RPC, context filtering, and UI blocking */

/**
 * Extracted action-button execution logic.
 *
 * Takes an {@link ActionManager} instance and accesses the service's
 * methods/state through it.
 */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { user } from "@web/services/user";

import { CTX_KEY_REGEX, EMBEDDED_ACTIONS_CTX_KEYS } from "./action_constants.js";

/** @typedef {Object} DoActionButtonParams */
/** @import { ActionManager } from "./action_service.js" */

export class InvalidButtonParamsError extends Error {}

/**
 * Sentinel resolved when a ``keepLast``-guarded button task is superseded by a
 * newer task on the same {@link KeepLast} (e.g. a programmatic ``doAction``
 * fired while the button's RPC was still in flight). KeepLast silently discards
 * the superseded wrapper — it never resolves nor rejects — so awaiting it
 * directly hangs the caller and, critically, skips the ``finally`` that releases
 * a ``block-ui`` overlay, stranding the full-screen spinner until a page reload.
 * Staying internal to this module, the sentinel is a plain resolve value and
 * never reaches the error service.
 *
 * @type {unique symbol}
 */
const SUPERSEDED = Symbol("action button superseded");

/**
 * Await a KeepLast-guarded task, resolving with {@link SUPERSEDED} instead of
 * hanging forever when the task is discarded by a newer one on the same
 * KeepLast. Callers must bail out (letting their ``finally`` run) on the
 * sentinel.
 *
 * @template T
 * @param {import("@web/core/utils/concurrency").KeepLast} keepLast
 * @param {Promise<T>} promise the raw task promise (always settles)
 * @returns {Promise<T | typeof SUPERSEDED>}
 */
function addOrSupersede(keepLast, promise) {
    // `keepLast.add` registers its `.then` on `promise` first; the guard below
    // registers second, so on a non-superseded settlement the wrapper resolves
    // `guarded` before the sentinel is produced and `guarded` wins the race
    // (an extra microtask makes that ordering robust). When superseded, the
    // wrapper stays pending forever and the sentinel resolves instead.
    const guarded = keepLast.add(promise);
    return Promise.race([
        guarded,
        promise.then(
            () => Promise.resolve().then(() => SUPERSEDED),
            () => Promise.resolve().then(() => SUPERSEDED),
        ),
    ]);
}

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
            // arch `args` is a Python-literal list (e.g. args="[1, 'foo']").
            // evaluateExpr parses Python literals natively, so single-quoted
            // strings and apostrophes inside strings round-trip correctly.
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
    // determine the action to execute according to the params
    let action;
    if (!isEmbeddedAction) {
        for (const key of EMBEDDED_ACTIONS_CTX_KEYS) {
            delete params.context?.[key];
        }
    }
    const context = makeContext([params.context, params.buttonContext]);
    const blockUi = exprToBoolean(params["block-ui"]);
    if (blockUi) {
        am.env.services.ui.block();
    }
    // Everything below runs inside a single try/finally so a `block-ui` overlay
    // is always released, whatever exit path is taken: a rejected
    // call_button/_loadAction RPC, an invalid-args or missing-type throw, or the
    // embedded-action early return. Without it, those paths stranded the
    // full-screen overlay (blockCount stuck at 1) until a page reload. `effect`
    // is declared here and triggered after the finally so the spinner is removed
    // before the effect plays.
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
            action = await addOrSupersede(am.keepLast, callProm);
            if (action === SUPERSEDED) {
                // A newer task discarded this one; bail out so the `finally`
                // releases the block-ui overlay instead of hanging forever.
                return;
            }
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
            action = await addOrSupersede(
                am.keepLast,
                am._loadAction(params.name, context),
            );
            if (action === SUPERSEDED) {
                // A newer task discarded this one; bail out so the `finally`
                // releases the block-ui overlay instead of hanging forever.
                return;
            }
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
        // filter out context keys that are specific to the current action, because:
        //  - wrong default_* and search_default_* values won't give the expected result
        //  - wrong group_by values will fail and forbid rendering of the destination view
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
