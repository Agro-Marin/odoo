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
 * Execute an action of type ``ir.actions.server``.
 *
 * Fires ``/web/action/run`` with the action id + merged context, gated by
 * ``am.keepLast`` so the latest server-action click wins if multiple are
 * in flight.  Defaults a null response to ``act_window_close`` so the
 * caller's promise chain still terminates cleanly.  Forwards the
 * originating ``action.path`` down to the next action for URL stability.
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
