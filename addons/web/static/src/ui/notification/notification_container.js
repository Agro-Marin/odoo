// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification_container */

import { Component, useState } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { Transition } from "@web/core/transition";
import { ErrorHandler } from "@web/core/utils/components";

import { Notification } from "./notification.js";
export class NotificationContainer extends Component {
    static serviceName = "notification";
    /**
     * The component this container renders each notification with. Its `props`
     * are the options `notificationService.add` accepts, so a subclass that
     * renders something else must say so here: deriving it from `components`
     * instead would validate against whatever is keyed `Notification`, which a
     * subclass inherits, and forward options the rendered component rejects.
     */
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
            this.props.notifications ?? this.serviceNotifications,
        );
    }

    /**
     * @returns {Record<number, { props: Object }>}
     */
    get serviceNotifications() {
        const { name, serviceName } = /** @type {any} */ (this.constructor);
        // eslint-disable-next-line no-restricted-syntax
        const service = this.env.services[serviceName];
        if (!service) {
            throw new Error(
                `${name}.serviceName is "${serviceName}", but no such service is started in this env. ` +
                    `A NotificationContainer subclass paired with its own service must declare that service's registry key.`,
            );
        }
        return service.notifications;
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
