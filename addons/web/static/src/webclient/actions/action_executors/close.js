// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/close */

/** @import { ActionManager } from "../action_service.js" */

/**
 * @param {ActionManager} am
 * @param {{ infos?: any }} [action]
 * @param {{ onClose?: (infos?: any) => any, dialog?: { remove: Function } }} [options]
 */
export function executeCloseAction(am, action = {}, options = {}) {
    if (options.dialog) {
        return am._removeDialog(action.infos, options.dialog.remove);
    }
    if (am.dialog) {
        return am._removeDialog(action.infos);
    }
    return options.onClose?.(action.infos);
}
