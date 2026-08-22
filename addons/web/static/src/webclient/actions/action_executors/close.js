// @ts-check
/** @odoo-module native */

/** @import { ActionManager } from "../action_service.js" */

/**
 * @param {ActionManager} am
 * @param {{ infos?: any }} [action]
 * @param {{ onClose?: (infos?: any) => any, dialog?: { remove: Function } | null }} [options]
 */
export function executeCloseAction(am, action = {}, options = {}) {
    if ("dialog" in options) {
        return options.dialog
            ? am._removeDialog(action.infos, options.dialog.remove)
            : undefined;
    }
    if (am.dialog) {
        return am._removeDialog(action.infos);
    }
    return options.onClose?.(action.infos);
}
