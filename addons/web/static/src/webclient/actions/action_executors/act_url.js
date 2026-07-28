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
 * Absolutize a bare relative url so ``isSafeUrlScheme`` sees a path rather
 * than something it could read as a scheme.
 *
 * @param {string} [url]
 * @returns {string} the empty string when there is no url to open
 */
function normalizeUrl(url) {
    if (!url) {
        return "";
    }
    return url.startsWith("http") || url.startsWith("/") ? url : `/${url}`;
}

/**
 * Execute an `ir.actions.act_url` action: redirect to the given URL.
 *
 * Targets:
 *   - "self"     — replace the current page (`location.assign`)
 *   - "download" — open in a new tab (file download); never chains a close,
 *                  since the download leaves the opener in place
 *   - default    — open in a new tab; if `action.close` is set, dispatch a
 *                  follow-up `ir.actions.act_window_close` so any wrapping
 *                  dialog closes
 *
 * SINGLE EXIT — ``options.onClose`` runs on every path.
 * Callers use it two ways: ``doActionButton`` forwards a view reload through
 * it, and ``doAction(..., { onClose: resolve })`` is how a caller awaits the
 * action (the same idiom ``chainOnClose`` in ``action_service`` protects). A
 * path that returns without settling it is therefore not "doing less" — it
 * strands the caller. Three did: a missing url, a blocked scheme, and
 * ``target="download"``. The close-chaining branch is the one early return,
 * and it hands ``onClose`` to the close action rather than dropping it.
 *
 * @param {ActURLAction} action
 * @param {ActionOptions} options the full caller options bag — the dispatcher
 *   in ``action_service`` forwards it verbatim to every executor, so narrowing
 *   this to the one key read here (``onClose``) made the dispatch map's value
 *   type incompatible with its own entries.
 * @param {ActionManager} am
 */
export function executeActURLAction(action, options, am) {
    const url = normalizeUrl(action.url);
    if (url && !isSafeUrlScheme(url)) {
        am.env.services.notification.add(
            _t("This action tried to open an unsafe URL and was blocked."),
            { sticky: true, type: "danger" },
        );
    } else if (url && action.target === "self") {
        browser.location.assign(url);
    } else if (url) {
        openURL(url, am);
        if (action.target !== "download" && action.close) {
            return am.doAction(
                { type: "ir.actions.act_window_close" },
                { onClose: options.onClose },
            );
        }
    }
    options.onClose?.();
}
