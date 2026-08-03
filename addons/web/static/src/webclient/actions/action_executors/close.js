// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/close */

/** @import { ActionManager } from "../action_service.js" */

/**
 * A caller that knows WHICH dialog it means passes a `dialog` key, and a
 * `null` there means "there was none" — not "close whatever is standing".
 * `doActionButton` captures `am.dialog` before its action runs, so for a
 * `close` button outside any dialog the key is present and null; falling
 * through to `am.dialog` closed the dialog the button's own action had just
 * opened.
 *
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
