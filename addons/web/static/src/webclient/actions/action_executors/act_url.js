// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";

import { actionStorage } from "../action_storage.js";

/** @import { ActionManager, ActionOptions, ActURLAction } from "../action_service.js" */

/**
 * @param {string} url
 * @param {ActionManager} am
 */
export function openURL(url, am) {
    const w = browser.open(url, "_blank");
    if (!w || w.closed) {
        const msg = _t(
            "A popup window has been blocked. You may need to change your " +
                "browser settings to allow popup windows for this page.",
        );
        am.notificationService.add(msg, {
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

const ACTION_URL_SCHEMES = ["blob"];

const HAS_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/**
 * @param {string} [url]
 * @returns {string}
 */
function normalizeUrl(url) {
    if (!url) {
        return "";
    }
    return url.startsWith("/") || HAS_SCHEME_RE.test(url) ? url : `/${url}`;
}

/**
 * @param {ActURLAction} action
 * @param {ActionOptions} options
 * @param {ActionManager} am
 */
export function executeActURLAction(action, options, am) {
    const url = isSafeUrlScheme(action.url ?? "", ACTION_URL_SCHEMES)
        ? normalizeUrl(action.url)
        : null;
    if (url === null) {
        am.notificationService.add(
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
