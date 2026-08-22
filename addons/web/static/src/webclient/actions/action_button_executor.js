// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { evaluateExpr } from "@web/core/py_js/py";
import { user } from "@web/core/user";
import { omit, pick } from "@web/core/utils/collections/objects";
import { exprToBoolean } from "@web/core/utils/format/strings";

import { CTX_KEY_REGEX, EMBEDDED_ACTIONS_CTX_KEYS } from "./action_constants.js";

/** @typedef {Object} DoActionButtonParams */
/** @import { ActionManager, Context } from "./action_service.js" */

export class InvalidButtonParamsError extends Error {}

/**
 * @param {DoActionButtonParams} params
 * @returns {any[]}
 * @throws {InvalidButtonParamsError}
 */
export function buildCallButtonArgs(params) {
    let args = params.resId ? [[params.resId]] : [params.resIds];
    if (params.args) {
        let additionalArgs;
        try {
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
 * @param {Context} [context]
 * @returns {Context}
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
 * @param {ActionManager} am
 * @param {DoActionButtonParams} params
 * @param {Context} context mutated in place for `type="action"`, which is where
 * the active_* keys the loaded action reads are seeded
 * @returns {Promise<any>}
 * @throws {InvalidButtonParamsError}
 */
async function resolveButtonAction(am, params, context) {
    if (params.special) {
        return { type: "ir.actions.act_window_close", infos: { special: true } };
    }
    if (params.type === "object") {
        const callProm = rpc(
            `/web/dataset/call_button/${params.resModel}/${params.name}`,
            {
                args: buildCallButtonArgs(params),
                kwargs: { context },
                method: params.name,
                model: params.resModel,
            },
        );
        const answer = await am.navigation.guard(callProm);
        const action =
            answer && typeof answer === "object"
                ? answer
                : { type: "ir.actions.act_window_close" };
        if (action.help) {
            action.help = markup(action.help);
        }
        return action;
    }
    if (params.type === "action") {
        context.active_id = params.resId ?? null;
        context.active_ids = params.resIds;
        context.active_model = params.resModel;
        return am.navigation.guard(am._loadAction(params.name, context));
    }
    throw new InvalidButtonParamsError("Missing type for doActionButton request");
}

/**
 * A button whose action carries embedded actions re-enters `doActionButton` on
 * the user's preferred one instead of opening the parent.
 *
 * @param {ActionManager} am
 * @param {any} action
 * @param {DoActionButtonParams} params
 * @param {boolean} [newWindow]
 * @returns {Promise<boolean>} whether an embedded action was dispatched, in
 * which case the caller has nothing left to do
 */
async function dispatchPreferredEmbeddedAction(am, action, params, newWindow) {
    if (!action.embedded_action_ids?.length) {
        return false;
    }
    const embeddedActionsKey = `${action.id}+${params.resId || ""}`;
    const embeddedActionsOrder =
        user.settings.embedded_actions_config_ids?.[embeddedActionsKey]
            ?.embedded_actions_order;
    const embeddedActionId = embeddedActionsOrder?.[0];
    const embeddedAction = action.embedded_action_ids.find(
        (candidate) => candidate.id === embeddedActionId,
    );
    if (!embeddedAction) {
        return false;
    }
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
        ...(embeddedAction.context ? makeContext([embeddedAction.context]) : {}),
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
            ...pick(params, "onClose", "close", "effect", "stackPosition"),
        },
        { isEmbeddedAction: true, newWindow },
    );
    return true;
}

/**
 * @param {ActionManager} am
 * @param {DoActionButtonParams} params
 * @param {Object} [options={}]
 * @param {boolean} [options.isEmbeddedAction]
 * @param {boolean} [options.newWindow]
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
    const dialogAtPress = am.dialog;
    let action;
    if (!isEmbeddedAction && params.context) {
        params = {
            ...params,
            context: omit(params.context, ...EMBEDDED_ACTIONS_CTX_KEYS),
        };
    }
    const context = makeContext([params.context, params.buttonContext]);
    const blockUi = exprToBoolean(params["block-ui"]);
    if (blockUi) {
        am.uiService.block();
    }
    let effect;
    try {
        action = await resolveButtonAction(am, params, context);
        if (
            !isEmbeddedAction &&
            (await dispatchPreferredEmbeddedAction(am, action, params, newWindow))
        ) {
            return;
        }
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
        effect = params.effect ? evaluateExpr(params.effect) : action.effect;
        const { onClose, stackPosition, viewType } = params;
        await am.doAction(action, {
            newWindow,
            onClose,
            onCloseIsSpeculative: true,
            stackPosition,
            viewType,
        });
        if (params.close) {
            await am._executeCloseAction(undefined, { dialog: dialogAtPress });
        }
    } finally {
        if (blockUi) {
            am.uiService.unblock();
        }
    }
    if (effect) {
        am.effectService.add(effect);
    }
}
