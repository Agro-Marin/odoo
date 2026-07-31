// @ts-check
/** @odoo-module native */

/** @module @web/views/widgets/notification_alert/notification_alert */

import { Component } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class NotificationAlert extends Component {
    static props = standardWidgetProps;
    static template = "web.NotificationAlert";

    get isNotificationBlocked() {
        return browser.Notification && browser.Notification.permission === "denied";
    }
}

/** @type {import("registries").ViewWidgetsRegistryItemShape} */
export const notificationAlert = {
    component: NotificationAlert,
};

registry.category("view_widgets").add("notification_alert", notificationAlert);
