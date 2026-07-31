// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification_service */

import { reactive } from "@odoo/owl";
import { mainComponentEntry } from "@web/components/main_components_container";
import { registry } from "@web/core/registry";

import { NotificationContainer } from "./notification_container.js";
/**
 * @typedef {Object} NotificationButton
 * @property {string} name
 * @property {string} [icon]
 * @property {boolean} [primary=false]
 * @property {function(): void} onClick
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
    notificationContainerKey: "NotificationContainer",

    start() {
        let notifId = 0;
        const notificationProps =
            this.notificationContainer.notificationComponent?.props;
        if (!notificationProps) {
            throw new Error(
                `${this.notificationContainer.name}.notificationComponent must declare the component ` +
                    `rendering each notification, so that the options this service accepts are the ` +
                    `props that component validates.`,
            );
        }
        /**
         * @type {Set<string>}
         */
        const declaredProps = new Set(Object.keys(notificationProps));
        const notifications = reactive(
            /**
             * @type {Record<number, { id: number, props: Record<string, any>, onClose?: () => void }>}
             */ ({}),
        );

        registry
            .category("main_components")
            .add(
                this.notificationContainerKey,
                mainComponentEntry(this.notificationContainer),
                { sequence: 100 },
            );

        /**
         * @param {string} message
         * @param {NotificationOptions} [options]
         */
        function add(message, options = {}) {
            const id = ++notifId;
            const closeFn = () => close(id);
            const props = /** @type {Record<string, any>} */ ({
                message,
                close: closeFn,
            });
            for (const [key, value] of Object.entries(options)) {
                if (key === "onClose") {
                    continue;
                }
                if (declaredProps.has(key)) {
                    props[key] = value;
                } else if (odoo.debug) {
                    console.warn(
                        `[notification] unknown option "${key}"; it will be ignored.`,
                    );
                }
            }
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
                try {
                    if (notification.onClose) {
                        notification.onClose();
                    }
                } finally {
                    delete notifications[id];
                }
            }
        }

        return {
            add,
            notifications,
            destroy() {
                for (const id of Object.keys(notifications)) {
                    close(Number(id));
                }
            },
        };
    },
};

registry.category("services").add("notification", notificationService);
