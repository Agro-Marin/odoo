// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/load_state - Restore the action stack from URL state and dispatch the leaf action */

import { browser } from "@web/core/browser/browser";
import { AppEvent } from "@web/core/events";
import { SupersededError } from "@web/core/utils/concurrency";
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
    // Navigation-intent guard for the back/forward race. `_controllersFromState`
    // below awaits a network round-trip (`/web/action/load_breadcrumbs`) OUTSIDE
    // the action manager's KeepLast, so two rapid popstates (e.g. back pressed
    // twice on a slow network) run two concurrent loadStates. Without a guard,
    // whichever reaches `doAction` LAST enters the KeepLast last and wins —
    // mounting the intermediate page and letting its pushState-on-mount rewrite
    // the URL back to the stale state. Snapshot the intent counter now (bumped
    // per loadState entry, so the final popstate holds the highest value) and,
    // once the breadcrumbs resolve, bail if a newer loadState superseded us.
    // (The window AFTER `doAction` enters the KeepLast is already covered by the
    // KeepLast's own supersession.)
    const generation = ++am._loadStateGeneration;
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
    if (am._loadStateGeneration !== generation) {
        // A newer loadState (a later popstate / route change) started while we
        // awaited the breadcrumb reconstruction. Signal supersession the same
        // way the KeepLast does: `WebClient.loadRouterState` and the global
        // error service both treat SupersededError as "a newer navigation owns
        // the UI now" and swallow it silently — never falling back to the
        // default app, which would fight the newer navigation.
        throw new SupersededError();
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
                if (state.actionStack?.length > 1) {
                    const newState = {
                        ...state.actionStack.slice(0, -1).at(-1),
                        actionStack: [...state.actionStack.slice(0, -1)],
                    };
                    return loadState(am, newState);
                } else {
                    // `state.actionStack` is absent for a bare `/odoo` URL that
                    // fell back to a (now-deleted) home action: optional-chain
                    // so a MissingActionError here reaches the intended silent
                    // default-app fallback instead of a TypeError dialog.
                    am.env.bus.trigger(AppEvent.WEBCLIENT_LOAD_DEFAULT_APP);
                }
            } else {
                throw error;
            }
        }
        return true;
    }
}
