// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/load_state - Restore the action stack from URL state and dispatch the leaf action */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { user } from "@web/services/user";

/** @import { ActionManager } from "./action_service.js" */

/**
 * Restore a stack of virtual controllers from the URL state object (usually
 * `router.current`) and dispatch a `doAction` on the leaf.  Used by:
 *
 *   - `WebClient.setup()` on initial page load to hydrate the action stack
 *     from the URL before mounting.
 *   - `web_studio/studio_service` when leaving Studio so the in-memory
 *     stack matches what the URL says.
 *   - `project_sharing` for the same purpose in the shared-project shell.
 *
 * Handles the `MissingActionError` case where the URL references an action
 * that no longer exists on the server: pop the leaf entry from
 * `state.actionStack` and recurse.  If the stack is empty, dispatch
 * `WEBCLIENT:LOAD_DEFAULT_APP` so the webclient falls back to the user's
 * default app.  Any other exception propagates to the caller.
 *
 * The `state` parameter defaults to `am.router.current` so external
 * callers can still invoke `actionService.loadState()` with no arguments.
 *
 * @param {ActionManager} am
 * @param {object} [state]
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
    const newStack = await am._controllersFromState(state);
    const actionParams = am._getActionParams(state);
    if (actionParams) {
        // Valid params → perform a doAction at the leaf.
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
