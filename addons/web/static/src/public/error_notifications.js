// @ts-check
/** @odoo-module native */

/** @module @web/public/error_notifications - Registers Odoo exception types as notification-style error handlers instead of dialogs */

import { odooExceptionTitleMap } from "@web/components/errors/error_dialogs";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
odooExceptionTitleMap.forEach((title, exceptionName) => {
    registry.category("error_notifications").add(exceptionName, {
        title: title,
        type: "warning",
        sticky: true,
    });
});

/**
 * The whole entry is handed to `notification.add` as its options, and `sticky`
 * defaults to false there: this one asks the visitor to confirm a reload, and
 * without it the prompt closed itself — button included — after the service's
 * 4s autoclose. Every other entry in this file already sets it.
 *
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
            click: () => window.location.reload(),
            close: true,
        },
    ],
};

/**
 * Forbidden (403) is an ACCESS DENIAL, not a session expiry: reusing the
 * session-expired config reloaded the page, which either loops or masks the
 * real permission problem. Give it a distinct, non-reloading message.
 * @type {{ title: string, message: string, type: string, sticky: boolean }}
 */
const forbidden = {
    title: _t("Access Denied"),
    message: _t("You do not have permission to perform this operation."),
    type: "warning",
    sticky: true,
};

registry
    .category("error_notifications")
    .add("odoo.http.SessionExpiredException", sessionExpired)
    .add("werkzeug.exceptions.Forbidden", forbidden);
