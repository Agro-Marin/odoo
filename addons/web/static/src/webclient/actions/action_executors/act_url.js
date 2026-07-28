// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_url - Executor for ir.actions.act_url + the shared _openURL / _openActionInNewWindow helpers */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";

import { actionStorage } from "../action_storage.js";

/** @import { ActionManager, ActionOptions, ActURLAction } from "../action_service.js" */

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
    actionStorage.withTemporaryEntry(
        { serializedAction: action._originalAction, state },
        () => openURL(am.router.stateToUrl(state), am),
    );
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
 * @param {ActionOptions} options the full caller options bag — the dispatcher
 *   in ``action_service`` forwards it verbatim to every executor, so narrowing
 *   this to the one key read here (``onClose``) made the dispatch map's value
 *   type incompatible with its own entries.
 * @param {ActionManager} am
 */
export function executeActURLAction(action, options, am) {
    let url = action.url;
    if (!url) {
        return;
    }
    if (!(url.startsWith("http") || url.startsWith("/"))) {
        url = "/" + url;
    }
    if (!isSafeUrlScheme(url)) {
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
