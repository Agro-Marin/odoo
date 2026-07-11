// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_button_executor - Executes action buttons (type=object/action/special) with RPC, context filtering, and UI blocking */

/**
 * Extracted action-button execution logic; takes an {@link ActionManager}
 * instance and accesses the service's methods/state through it.
 */

import { markup } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { makeContext } from "@web/core/context";
import { AppEvent } from "@web/core/events";
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
 * Sentinel for a {@link KeepLast}-guarded button task superseded by a newer
 * task on the same KeepLast (e.g. a ``doAction`` fired while the RPC was in
 * flight). KeepLast silently discards the superseded wrapper — never
 * resolving nor rejecting — so awaiting it directly hangs and skips the
 * ``finally`` that releases the ``block-ui`` overlay.
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
    // `keepLast.add` registers its `.then` first, so on a non-superseded
    // settlement `guarded` resolves before the sentinel and wins the race
    // (an extra microtask makes that robust). When superseded, `guarded`
    // stays pending forever and the sentinel resolves instead.
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
 * Await a ``doAction`` promise, resolving with {@link SUPERSEDED} instead of
 * hanging forever when the dispatched action is superseded — either its
 * internal KeepLast wrapper is discarded, or its controller is replaced by a
 * newer ``ACTION_MANAGER:UPDATE`` before mounting; in both cases the promise
 * never settles, so {@link addOrSupersede} (which races on the raw promise's
 * own settlement) cannot guard this phase. Instead, any completed action
 * render (``ACTION_MANAGER_UI_UPDATED`` — the same supersession signal
 * ``webclient.js`` uses for its pointer-events escape hatch) arms a macrotask
 * check: the macrotask drains every pending microtask first, so a promise
 * that was merely propagating through its async layers settles and wins the
 * race, while a genuinely superseded one resolves the sentinel.
 *
 * @param {ActionManager} am
 * @param {Promise<any>} promise the raw ``doAction`` promise (may never settle)
 * @returns {Promise<any | typeof SUPERSEDED>}
 */
function awaitActionOrSupersede(am, promise) {
    return new Promise((resolve, reject) => {
        let done = false;
        const finish = (callback, value) => {
            if (!done) {
                done = true;
                am.env.bus.removeEventListener(
                    AppEvent.ACTION_MANAGER_UI_UPDATED,
                    onUiUpdated,
                );
                callback(value);
            }
        };
        const onUiUpdated = () => {
            // This may be our own action mounting (its resolve() runs just
            // before the trigger): give the promise a full macrotask to
            // settle through its async layers before declaring supersession.
            browser.setTimeout(() => finish(resolve, SUPERSEDED));
        };
        am.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UI_UPDATED, onUiUpdated);
        promise.then(
            (value) => finish(resolve, value),
            (error) => finish(reject, error),
        );
    });
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
        const result = await awaitActionOrSupersede(
            am,
            am.doAction(action, {
                newWindow,
                onClose,
                stackPosition,
                viewType,
            }),
        );
        if (result === SUPERSEDED) {
            // A newer action rendered before this one; bail out so the
            // `finally` releases the block-ui overlay instead of hanging forever.
            return;
        }
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
