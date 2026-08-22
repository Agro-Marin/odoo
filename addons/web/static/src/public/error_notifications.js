// @ts-check
/** @odoo-module native */

import { odooExceptionTitleMap } from "@web/components/errors/error_dialogs";
import { registry } from "@web/core/registry";
import { registerErrorNotifications } from "@web/public/error_notifications_registry";

registerErrorNotifications(
    registry.category("error_notifications"),
    odooExceptionTitleMap,
);
