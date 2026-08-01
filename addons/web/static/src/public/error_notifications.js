// @ts-check
/** @odoo-module native */

/** @module @web/public/error_notifications */

import { odooExceptionTitleMap } from "@web/components/errors/error_dialogs";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

/**
 * @type {{ title: string, message: string, type: string, sticky: boolean, buttons: Array<{ text: string, click: () => void, close: boolean }> }}
 */
const sessionExpired = {
    title: _t("Odoo Session Expired"),
    message: _t(
        "Your Odoo session expired. The current page is about to be refreshed.",
    ),
    type: "warning",
    sticky: true,
    buttons: [
        {
            text: _t("Ok"),
            click: () => browser.location.reload(),
            close: true,
        },
    ],
};

/**
 * @type {{ title: string, message: string, type: string, sticky: boolean }}
 */
const forbidden = {
    title: _t("Access Denied"),
    message: _t("You do not have permission to perform this operation."),
    type: "warning",
    sticky: true,
};

const notifications = registry.category("error_notifications");
odooExceptionTitleMap.forEach((title, exceptionName) => {
    notifications.add(exceptionName, {
        title: title,
        type: "warning",
        sticky: true,
    });
});
notifications
    .add("odoo.http.SessionExpiredException", sessionExpired, { force: true })
    .add("werkzeug.exceptions.Forbidden", forbidden, { force: true });
