// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/server - Executor for ir.actions.server */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/services/user";

/** @import { ActionManager } from "../action_service.js" */
/** @import { ServerAction } from "@web/webclient/actions/action_service" */

/**
 * Execute an ``ir.actions.server`` action via ``/web/action/run``, gated by
 * ``am.keepLast`` so only the latest click wins. Defaults a null response to
 * ``act_window_close``, and forwards ``action.path`` for URL stability.
 *
 * @param {ServerAction} action
 * @param {object} options
 * @param {ActionManager} am
 */
export async function executeServerAction(action, options, am) {
    const runProm = rpc("/web/action/run", {
        action_id: action.id,
        context: makeContext([user.context, action.context]),
    });
    let nextAction = await am.keepLast.add(runProm);
    nextAction = nextAction || { type: "ir.actions.act_window_close" };
    if (nextAction.help) {
        nextAction.help = markup(nextAction.help);
    }
    if (typeof nextAction === "object") {
        nextAction.path ||= action.path;
    }
    return /** @type {any} */ (am.doAction(nextAction, options));
}
