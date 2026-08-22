// @ts-check
/** @odoo-module native */

import { AppEvent } from "@web/core/events";
import { user } from "@web/core/user";

import { actionStorage } from "./action_storage.js";

/** @import { ActionManager } from "./action_service.js" */

/**
 * @param {any[]} controllers
 * @param {Record<string, any>} state
 * @param {number} popped
 * @returns {any[]}
 */
function crumbsBelowDispatched(controllers, state, popped) {
    const dispatched = state.actionStack.length - 1 - popped;
    return controllers.filter((controller) => controller.stackIndex < dispatched);
}

/**
 * @param {ActionManager} am
 * @param {Record<string, any>} [state]
 * @returns {Promise<boolean | undefined>}
 */
export async function loadState(am, state) {
    /** @type {Record<string, any>} */
    const routeState = state ?? am.router.current;
    const token = am.navigation.mint();
    const lang = actionStorage.getLang();
    if (lang && lang !== user.lang) {
        actionStorage.clearRestoreCache();
    }
    /** @type {any[]} */
    let newStack;
    try {
        newStack = await am._controllersFromState(routeState);
    } catch (error) {
        console.warn(
            "Failed to restore the action stack from the url state; " +
                "loading the last action without breadcrumbs.",
            error,
        );
        newStack = [];
    }
    token.throwIfSuperseded();
    const actionParams = am._getActionParams(routeState);
    if (actionParams) {
        const { actionRequest, options } = actionParams;
        const popped = options.poppedLeaves || 0;
        delete options.poppedLeaves;
        options.newStack = popped
            ? crumbsBelowDispatched(newStack, routeState, popped)
            : newStack;
        try {
            await am.doAction(actionRequest, options);
        } catch (error) {
            if (
                error.exceptionName ===
                "odoo.addons.web.controllers.action.MissingActionError"
            ) {
                const actionStack = routeState?.actionStack;
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
