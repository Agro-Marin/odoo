// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_url - Executor for ir.actions.act_url + the shared _openURL / _openActionInNewWindow helpers */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";

/** @import { ActionManager } from "../action_service.js" */
/** @import { ActURLAction } from "@web/webclient/actions/action_service" */

/**
 * Open `url` in a new browser tab/window via `window.open`.  When the popup
 * is blocked (most browsers return null/closed), surface a sticky warning
 * notification — the action is silently lost without it.
 *
 * @param {string} url
 * @param {ActionManager} am
 */
export function openURL(url, am) {
    const w = browser.open(url, "_blank");
    if (!w || w.closed || typeof w.closed === "undefined") {
        const msg = _t(
            "A popup window has been blocked. You may need to change your " +
                "browser settings to allow popup windows for this page.",
        );
        am.env.services.notification.add(msg, {
            sticky: true,
            type: "warning",
        });
    }
}

/**
 * Open the given action in a new tab by serializing it through sessionStorage
 * (which is duplicated by the spec into the new auxiliary browsing context).
 *
 * Saves and restores the current window's `current_action` / `current_state`
 * keys so the originating window's state isn't clobbered while the destination
 * window initializes.
 *
 * @param {object} action
 * @param {object} state
 * @param {ActionManager} am
 */
export function openActionInNewWindow(action, state, am) {
    // Session storage is duplicated in the new window per the HTML spec:
    // https://html.spec.whatwg.org/multipage/webstorage.html#webstorage
    const currentAction = browser.sessionStorage.getItem("current_action");
    const currentState = browser.sessionStorage.getItem("current_state");
    // Store on the session the action for the new window
    browser.sessionStorage.setItem("current_action", action._originalAction || "{}");
    browser.sessionStorage.setItem("current_state", JSON.stringify(state));
    openURL(am.router.stateToUrl(state), am);
    // Restore the current action of the originating window
    if (currentAction !== null) {
        browser.sessionStorage.setItem("current_action", currentAction);
    } else {
        browser.sessionStorage.removeItem("current_action");
    }
    if (currentState !== null) {
        browser.sessionStorage.setItem("current_state", currentState);
    } else {
        browser.sessionStorage.removeItem("current_state");
    }
}

/**
 * Execute an `ir.actions.act_url` action: redirect to the given URL.
 *
 * Targets:
 *   - "self"     — replace the current page (`location.assign`)
 *   - "download" — open in a new tab (file download)
 *   - default    — open in a new tab; if `action.close` is set, dispatch a
 *                  follow-up `ir.actions.act_window_close` so any wrapping
 *                  dialog closes.  Otherwise just invoke `options.onClose`.
 *
 * @param {ActURLAction} action
 * @param {{ onClose?: () => any }} options
 * @param {ActionManager} am
 */
export function executeActURLAction(action, options, am) {
    let url = action.url;
    if (url && !(url.startsWith("http") || url.startsWith("/"))) {
        url = "/" + url;
    }
    // Block protocol-relative (//host) and script-bearing schemes before
    // navigating; legitimate relative/http(s) targets are unaffected.
    if (url && !isSafeUrlScheme(url)) {
        am.env.services.notification.add(
            _t("This action tried to open an unsafe URL and was blocked."),
            { sticky: true, type: "danger" },
        );
        return;
    }
    if (action.target === "self") {
        browser.location.assign(url);
    } else if (action.target === "download") {
        openURL(url, am);
    } else {
        openURL(url, am);
        if (action.close) {
            return am.doAction(
                { type: "ir.actions.act_window_close" },
                { onClose: options.onClose },
            );
        } else if (options.onClose) {
            options.onClose();
        }
    }
}
