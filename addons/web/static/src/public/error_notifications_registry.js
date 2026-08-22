// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";

/**
 * @type {import("registries").ErrorNotificationsRegistryItemShape}
 */
export const sessionExpired = {
    title: _t("Odoo Session Expired"),
    message: _t(
        "Your Odoo session expired. The current page is about to be refreshed.",
    ),
    type: "warning",
    sticky: true,
    buttons: [
        {
            name: _t("Ok"),
            onClick: () => browser.location.reload(),
        },
    ],
};

/**
 * @type {import("registries").ErrorNotificationsRegistryItemShape}
 */
export const forbidden = {
    title: _t("Access Denied"),
    message: _t("You do not have permission to perform this operation."),
    type: "warning",
    sticky: true,
};

export const OVERRIDDEN_EXCEPTIONS = {
    "odoo.http.SessionExpiredException": sessionExpired,
    "werkzeug.exceptions.Forbidden": forbidden,
};

/**
 * @param {{ add: (name: string, value: any, options?: object) => any }} notifications
 * @param {Map<string, string>} titleMap
 * @returns {void}
 */
export function registerErrorNotifications(notifications, titleMap) {
    titleMap.forEach((title, exceptionName) => {
        notifications.add(exceptionName, {
            title,
            type: "warning",
            sticky: true,
        });
    });
    for (const [name, presentation] of Object.entries(OVERRIDDEN_EXCEPTIONS)) {
        notifications.add(name, presentation, { force: true });
    }
}
