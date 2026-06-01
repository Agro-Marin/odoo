// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/close - Executor for ir.actions.act_window_close */

/** @import { ActionManager } from "../action_service.js" */

/**
 * Execute an action of type ``ir.actions.act_window_close``.
 *
 * Two paths:
 *   - A modal dialog is open → close it (the dialog's own ``onClose``
 *     fires from inside ``_removeDialog``).
 *   - No dialog → invoke the caller-supplied ``options.onClose`` (used by
 *     ``ir.actions.act_url`` flows that want to tear down a previous
 *     dialog after redirecting).
 *
 * Reading ``am.dialog`` directly (rather than capturing a value at
 * call-construction time) is required because the action manager holds
 * the dialog reference as mutable instance state; the value at
 * executor-call time is what matters.
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
