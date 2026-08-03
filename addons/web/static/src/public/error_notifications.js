// @ts-check
/** @odoo-module native */

/** @module @web/public/error_notifications */

import { odooExceptionTitleMap } from "@web/components/errors/error_dialogs";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

/**
 * @type {import("registries").ErrorNotificationsRegistryItemShape}
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
            name: _t("Ok"),
            onClick: () => browser.location.reload(),
        },
    ],
};

/**
 * @type {import("registries").ErrorNotificationsRegistryItemShape}
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
