// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/load_state */

import { AppEvent } from "@web/core/events";
import { SupersededError } from "@web/core/utils/concurrency";
import { user } from "@web/services/user";

import { actionStorage } from "./action_storage.js";

/** @import { ActionManager } from "./action_service.js" */

/**
 * @param {ActionManager} am
 * @param {Record<string, any>} [state]
 * @returns {Promise<boolean | undefined>}
 */
export async function loadState(am, state) {
    state ??= am.router.current;
    const generation = ++am._loadStateGeneration;
    const lang = actionStorage.getLang();
    if (lang && lang !== user.lang) {
        actionStorage.clearRestoreCache();
    }
    /** @type {any[]} */
    let newStack;
    try {
        newStack = await am._controllersFromState(state);
    } catch (error) {
        console.warn(
            "Failed to restore the action stack from the url state; " +
                "loading the last action without breadcrumbs.",
            error,
        );
        newStack = [];
    }
    if (am._loadStateGeneration !== generation) {
        throw new SupersededError();
    }
    const actionParams = am._getActionParams(state);
    if (actionParams) {
        const { actionRequest, options } = actionParams;
        const popped = options.poppedLeaves || 0;
        delete options.poppedLeaves;
        options.newStack = popped ? newStack.slice(0, -popped) : newStack;
        try {
            await am.doAction(actionRequest, options);
        } catch (error) {
            if (
                error.exceptionName ===
                "odoo.addons.web.controllers.action.MissingActionError"
            ) {
                const actionStack = state?.actionStack;
                if (actionStack?.length > 1) {
                    const newState = {
                        ...actionStack.slice(0, -1).at(-1),
                        actionStack: [...actionStack.slice(0, -1)],
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
