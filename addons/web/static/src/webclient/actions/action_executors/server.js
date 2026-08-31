// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";

import { nextActionDepth } from "../action_constants.js";

/** @import { ActionManager } from "../action_service.js" */
/** @import { ServerAction } from "@web/webclient/actions/action_service" */

/**
 * @param {ServerAction} action
 * @param {{ _actionDepth?: number } & object} options
 * @param {ActionManager} am
 */
export async function executeServerAction(action, options, am) {
    const runProm = rpc("/web/action/run", {
        action_id: action.id,
        context: makeContext([user.context, action.context]),
    });
    let nextAction = await am.navigation.guard(runProm);
    nextAction = nextAction || { type: "ir.actions.act_window_close" };
    if (nextAction.help) {
        nextAction.help = markup(nextAction.help);
    }
    // Load-bearing, despite reading as defensive noise: `/web/action/run` may
    // answer with a bare action **id** rather than a dict, and assigning to a
    // primitive throws under the module's implicit strict mode. The `.help`
    // read above survives one only because reading a property off a number is
    // legal where writing one is not.
    // Covered by server_action.test.js "can execute server actions from db ID".
    if (typeof nextAction === "object") {
        nextAction.path ||= action.path;
    }
    const depth = nextActionDepth(options);
    return /** @type {any} */ (
        am.doAction(nextAction, { ...options, _actionDepth: depth })
    );
}
