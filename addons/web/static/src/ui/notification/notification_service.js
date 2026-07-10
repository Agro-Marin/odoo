// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification_service - Service that manages toast notifications displayed in the top-right corner */

import { reactive } from "@odoo/owl";
import { registry } from "@web/core/registry";

import { NotificationContainer } from "./notification_container.js";
/**
 * @typedef {Object} NotificationButton
 * @property {string} name
 * @property {string} [icon]
 * @property {boolean} [primary=false]
 * @property {function(): void} onClick
 *
 * @typedef {Object} NotificationOptions
 * @property {string} [title]
 * @property {number} [autocloseDelay=4000]
 * @property {"warning" | "danger" | "success" | "info"} [type]
 * @property {boolean} [sticky=false]
 * @property {string} [className]
 * @property {function(): void} [onClose]
 * @property {NotificationButton[]} [buttons]
 */

export const notificationService = {
    notificationContainer: NotificationContainer,

    start() {
        let notifId = 0;
        const notifications = reactive(
            /** @type {Record<number, { id: number, props: Record<string, any>, onClose?: () => void }>} */ ({}),
        );

        registry.category("main_components").add(
            this.notificationContainer.name,
            {
                Component: this.notificationContainer,
                props: { notifications },
            },
            { sequence: 100 },
        );

        /**
         * @param {string} message
         * @param {NotificationOptions} [options]
         */
        function add(message, options = {}) {
            const id = ++notifId;
            const closeFn = () => close(id);
            const props = { ...options, message, close: closeFn };
            delete props.onClose;
            const notification = {
                id,
                props,
                onClose: options.onClose,
            };
            notifications[id] = notification;
            return closeFn;
        }

        /**
         * @param {number} id
         */
        function close(id) {
            if (notifications[id]) {
                const notification = notifications[id];
                // The user-provided onClose may throw; the toast must still
                // be removed or it becomes permanently un-dismissable (same
                // hardening as dialog_service's onClose handling).
                try {
                    if (notification.onClose) {
                        notification.onClose();
                    }
                } finally {
                    delete notifications[id];
                }
            }
        }

        return { add };
    },
};

registry.category("services").add("notification", notificationService);
