// @ts-check
/** @odoo-module native */

import { markup } from "@odoo/owl";

/**
 * An action's `help` is server-rendered HTML the client must display as such;
 * every place an action arrives from the server marks it once.
 * @template {{ help?: any }} T
 * @param {T} action
 * @returns {T}
 */
export function withMarkupHelp(action) {
    if (action.help) {
        action.help = markup(action.help);
    }
    return action;
}
