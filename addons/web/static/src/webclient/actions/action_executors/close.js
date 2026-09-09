// @ts-check
/** @odoo-module native */

/**
 * @param {ActionManager} am
 * @param {{ infos?: any }} [action]
 * @param {{ onClose?: (infos?: any) => any, dialog?: { remove: Function } | null }} [options]
 */
export function executeCloseAction(am, action = {}, options = {}) {
    if ("dialog" in options) {
        return options.dialog
            ? am.removeDialog(action.infos, options.dialog.remove)
            : undefined;
    }
    if (am.dialog) {
        return am.removeDialog(action.infos);
    }
    return options.onClose?.(action.infos);
}
