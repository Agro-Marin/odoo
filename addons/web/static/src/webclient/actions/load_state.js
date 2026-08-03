// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/load_state */

import { AppEvent } from "@web/core/events";
import { user } from "@web/core/user";
import { SupersededError } from "@web/core/utils/concurrency";

import { actionStorage } from "./action_storage.js";

/** @import { ActionManager } from "./action_service.js" */

/**
 * The crumbs that sit below the action `getActionParams` settled on.
 *
 * `poppedLeaves` counts entries of the url's `actionStack`; the controller list
 * is shorter than that stack whenever `loadBreadcrumbs` could not name a crumb
 * and dropped it. Dropping the last `popped` SURVIVORS mixed the two, and cut
 * one crumb too many as soon as a drop landed inside the popped tail — the
 * common case being a leaf that popped BECAUSE its record was unreadable, which
 * is also why the server could not name it. Each controller carries the index
 * it was built from, so the cut is made where `poppedLeaves` was measured.
 *
 * Only ever reached with a `popped` that `getActionParams` produced, and it
 * only pops inside `actionStack?.length > 1` — so the stack it needs is there.
 * `controllersFromState` may have indexed against a state it took from
 * `actionStorage` instead of this one, but only after finding the two render
 * to the same url, and a url carries the whole stack.
 *
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
    const routeState = state ?? am.router.current;
    const generation = ++am._loadStateGeneration;
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
    if (am._loadStateGeneration !== generation) {
        throw new SupersededError();
    }
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
                // `routeState`, not the `state` parameter. `state` is optional
                // and is undefined on the initial load, which is exactly when a
                // url naming a missing action is most likely -- a stale link or
                // a pasted one. Reading it there made `actionStack` undefined,
                // so the "fall back to the previous action" arm was skipped and
                // the `else` silently loaded the default app instead. Every
                // other read in this function already goes through the resolved
                // state; this one was the odd one out.
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
