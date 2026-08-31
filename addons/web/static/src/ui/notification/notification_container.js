// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { Transition } from "@web/core/transition";
import { ErrorHandler } from "@web/core/utils/components";
import { serviceBackedItems } from "@web/ui/service_backed_items";

import { Notification } from "./notification.js";
export class NotificationContainer extends Component {
    static serviceName = "notification";
    static itemsKey = "notifications";
    static notificationComponent = Notification;
    static props = {
        notifications: { type: Object, optional: true },
    };

    static template = "web.NotificationContainer";
    static components = { ErrorHandler, Notification, Transition };

    /** @type {any} */
    notifications;

    setup() {
        /** @type {Object<string, { props: Object }>} */
        this.notifications = useState(
            serviceBackedItems(this, this.props.notifications),
        );
    }

    /**
     * @param {string} key
     * @param {Error} error
     */
    handleError(key, error) {
        this.notifications[key]?.props.close();
        reportUncaught(error);
    }
}
