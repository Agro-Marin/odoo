// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/close - Executor for ir.actions.act_window_close */

/** @import { ActionManager } from "../action_service.js" */

/**
 * Execute an ``ir.actions.act_window_close`` action: close the open dialog
 * if any, otherwise call the caller-supplied ``options.onClose`` (used by
 * ``ir.actions.act_url`` flows tearing down a previous dialog on redirect).
 *
 * ``am.dialog`` is read live, not captured earlier, since the action
 * manager mutates it as instance state.
 *
 * @param {ActionManager} am
 * @param {{ infos?: any }} [action]
 * @param {{ onClose?: (infos?: any) => any }} [options]
 */
export function executeCloseAction(am, action = {}, options = {}) {
    if (am.dialog) {
        return am._removeDialog(action.infos);
    }
    return options.onClose?.(action.infos);
}
