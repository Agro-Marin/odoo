// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_url */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";

import { actionStorage } from "../action_storage.js";

/** @import { ActionManager, ActionOptions, ActURLAction } from "../action_service.js" */

/**
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
 * @param {Record<string, any>} action
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
 * @param {string} [url]
 * @returns {string}
 */
function normalizeUrl(url) {
    if (!url) {
        return "";
    }
    return url.startsWith("http") || url.startsWith("/") ? url : `/${url}`;
}

/**
 * @param {ActURLAction} action
 * @param {ActionOptions} options
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
