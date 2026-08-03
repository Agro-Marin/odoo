// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_executors/act_url */

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
 * Schemes an action may target that are not safe to render as data. See
 * {@link isSafeUrlScheme}.
 */
const ACTION_URL_SCHEMES = ["blob"];

const HAS_SCHEME_RE = /^[a-z][a-z0-9+.-]*:/i;

/**
 * A bare `my/report` names a path on this server, so it gets the slash it is
 * missing. Anything that already carries a scheme is left alone: matching on
 * `startsWith("http")` let `blob:…` through as a relative path, and the pdf
 * viewer's download of a not-yet-saved upload could only ever 404.
 *
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
    // Checked before normalizing, not after: `normalizeUrl` prefixes anything
    // without an http/`/` head with a slash, which turns `javascript:alert(1)`
    // into the relative path `/javascript:alert(1)` — no scheme left for
    // `isSafeUrlScheme` to see. The guard then caught only what already looked
    // like a URL (`//host`, `httpx://`), never the scheme family it is for.
    const url = isSafeUrlScheme(action.url ?? "", ACTION_URL_SCHEMES)
        ? normalizeUrl(action.url)
        : null;
    if (url === null) {
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
