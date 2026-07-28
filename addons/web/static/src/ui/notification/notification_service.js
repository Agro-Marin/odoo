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
    /**
     * Explicit, because `website_sale` starts a second notification service
     * alongside this one and the two containers must land in different
     * `main_components` slots. Deriving the key from `Component.name` made
     * that separation depend on the bundler preserving class names.
     */
    notificationContainerKey: "NotificationContainer",

    start() {
        let notifId = 0;
        /**
         * Read off the hosted component's own declaration, never hardcoded:
         * this service is built to be subclassed with a different container
         * and notification component (`website_sale`'s cart toast takes
         * `lines`, `warning`, `currency_id`), so a fixed list here would
         * quietly strip exactly the props that subclass exists for.
         * `null` = the component declares nothing, so filter nothing.
         * @type {Set<string> | null}
         */
        const declaredProps = this.notificationContainer.components?.Notification?.props
            ? new Set(
                  Object.keys(this.notificationContainer.components.Notification.props),
              )
            : null;
        const notifications = reactive(
            /** @type {Record<number, { id: number, props: Record<string, any>, onClose?: () => void }>} */ ({}),
        );

        registry.category("main_components").add(
            this.notificationContainerKey,
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
            /**
             * Picked, not spread: every option used to become a prop, so one
             * unrecognised key made Owl reject the whole component and the
             * container dropped the notification — the caller lost their toast
             * outright, and only in debug mode, where prop validation runs.
             * Unknown keys now warn there instead, like `makeOverlayPresenter`
             * already does for overlay options.
             */
            const props = { message, close: closeFn };
            for (const [key, value] of Object.entries(options)) {
                if (key === "onClose") {
                    continue;
                }
                if (!declaredProps || declaredProps.has(key)) {
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

        return { add };
    },
};

registry.category("services").add("notification", notificationService);
