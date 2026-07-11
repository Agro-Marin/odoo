// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/load_state - Restore the action stack from URL state and dispatch the leaf action */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { user } from "@web/services/user";

/** @import { ActionManager } from "./action_service.js" */

/**
 * Restore a stack of virtual controllers from the URL state (usually
 * `router.current`) and dispatch a `doAction` on the leaf. Used to hydrate
 * the action stack from the URL on initial load, and by Studio /
 * project_sharing when leaving to resync the stack with the URL.
 *
 * On `MissingActionError` (URL references a deleted action), pops the leaf
 * from `state.actionStack` and recurses; if the stack is empty, triggers
 * `WEBCLIENT:LOAD_DEFAULT_APP`. Other errors propagate.
 *
 * @param {ActionManager} am
 * @param {object} [state] defaults to `am.router.current`
 * @returns {Promise<boolean | undefined>} true if a `doAction` was performed
 */
export async function loadState(am, state) {
    state ??= am.router.current;
    const lang = browser.sessionStorage.getItem("current_lang");
    if (lang && lang !== user.lang) {
        browser.sessionStorage.removeItem("current_action");
        browser.sessionStorage.removeItem("current_lang");
        browser.sessionStorage.removeItem("current_state");
    }
    let newStack;
    try {
        newStack = await am._controllersFromState(state);
    } catch (error) {
        // A failed breadcrumb reconstruction must not turn the restore into
        // a blank page: the leaf action can still load without its ancestry.
        console.warn(
            "Failed to restore the action stack from the url state; " +
                "loading the last action without breadcrumbs.",
            error,
        );
        newStack = [];
    }
    const actionParams = am._getActionParams(state);
    if (actionParams) {
        const { actionRequest, options } = actionParams;
        if (options.index !== undefined) {
            options.newStack = newStack.slice(0, options.index);
            delete options.index;
        } else {
            options.newStack = newStack;
        }
        try {
            await am.doAction(actionRequest, options);
        } catch (error) {
            if (
                error.exceptionName ===
                "odoo.addons.web.controllers.action.MissingActionError"
            ) {
                if (state.actionStack.length > 1) {
                    const newState = {
                        ...state.actionStack.slice(0, -1).at(-1),
                        actionStack: [...state.actionStack.slice(0, -1)],
                    };
                    return loadState(am, newState);
                } else {
                    am.env.bus.trigger(AppEvent.WEBCLIENT_LOAD_DEFAULT_APP);
                }
            } else {
                throw error;
            }
        }
        return true;
    }
}
