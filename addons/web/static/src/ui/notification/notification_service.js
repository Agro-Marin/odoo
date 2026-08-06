// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification_service */

import { reactive } from "@odoo/owl";
import { reportUncaught } from "@web/core/errors/error_utils";
import { registry } from "@web/core/registry";
import { mainComponentEntry } from "@web/ui/main_components_container";

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

/** Read by the service itself rather than forwarded to the component. */
const SERVICE_OPTIONS = new Set(["onClose"]);

/**
 * Written by the service on every notification. They are declared props, so the
 * option loop -- which copies anything the component declares -- used to accept
 * them from a caller and, running after the service had set them, win: an
 * `add(msg, { close })` left the ✕ button calling the caller's function, so the
 * notification could not be dismissed and stayed for the session.
 */
const SERVICE_OWNED_PROPS = new Set(["close", "message"]);

/**
 * The `notification` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * **`notificationContainer` and `notificationContainerKey` stay on the service
 * object below**, and `start()` passes them in. They are the service's
 * extension points — `website_sale` replaces both to render cart notifications,
 * and two suites do the same — so they must be read off whatever object owns
 * `start`, exactly as the closure did, and at the same moment: once, at start.
 * This is hazard 1 again, in the same shape as `fileUploadService.createXhr`.
 */
export class NotificationService {
    /**
     * @param {any} notificationContainer
     * @param {string} notificationContainerKey
     */
    constructor(notificationContainer, notificationContainerKey) {
        this.notifId = 0;
        const notificationProps = notificationContainer.notificationComponent?.props;
        if (!notificationProps) {
            throw new Error(
                `${notificationContainer.name}.notificationComponent must declare the component ` +
                    `rendering each notification, so that the options this service accepts are the ` +
                    `props that component validates.`,
            );
        }
        /** @type {Set<string>} */
        this.declaredProps = new Set(Object.keys(notificationProps));
        this.notifications = reactive(
            /**
             * @type {Record<number, { id: number, props: Record<string, any>, onClose?: () => void }>}
             */ ({}),
        );

        registry
            .category("main_components")
            .add(notificationContainerKey, mainComponentEntry(notificationContainer), {
                sequence: 100,
            });
    }

    /**
     * `message` is not just a string, and never was: `Notification`'s own prop
     * validator accepts `typeof m === "string" || (typeof m === "object" &&
     * typeof m.toString === "function")`, which is how `markup` messages render.
     * The closure declared `{string}` and nothing checked it; typing the method
     * for real made the mismatch visible, so this widens to what the component
     * actually validates rather than narrowing the callers to fit a wrong type.
     *
     * @param {string | { toString(): string }} message
     * @param {NotificationOptions} [options]
     * @returns {() => void}
     */
    add(message, options = {}) {
        const id = ++this.notifId;
        const closeFn = () => this._close(id);
        const props = /** @type {Record<string, any>} */ ({
            message,
            close: closeFn,
        });
        for (const [key, value] of Object.entries(options)) {
            if (SERVICE_OPTIONS.has(key)) {
                continue;
            }
            if (SERVICE_OWNED_PROPS.has(key)) {
                if (odoo.debug) {
                    console.warn(
                        `[notification] option "${key}" is set by the service; it will be ignored.`,
                    );
                }
                continue;
            }
            if (this.declaredProps.has(key)) {
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
        this.notifications[id] = notification;
        return closeFn;
    }

    /**
     * Underscored because it was never a published entry point: the closure
     * this replaced returned `{ add, notifications, destroy }` and kept `close`
     * inside. A class exposes every method on its prototype, so keeping the name
     * bare would have quietly widened the service's surface — the one way a
     * conversion can change behaviour without changing a line of logic.
     * Callers close a notification with the function `add()` hands back.
     *
     * @param {number} id
     */
    _close(id) {
        if (this.notifications[id]) {
            const notification = this.notifications[id];
            try {
                if (notification.onClose) {
                    notification.onClose();
                }
            } catch (error) {
                // A throwing `onClose` must not propagate into the caller —
                // the error service closes notifications mid-error-handling.
                reportUncaught(error);
            } finally {
                delete this.notifications[id];
            }
        }
    }

    destroy() {
        for (const id of Object.keys(this.notifications)) {
            this._close(Number(id));
        }
    }
}

export const notificationService = {
    notificationContainer: NotificationContainer,
    notificationContainerKey: "NotificationContainer",

    /**
     * @returns {NotificationService}
     */
    start() {
        return new NotificationService(
            this.notificationContainer,
            this.notificationContainerKey,
        );
    },
};

registry.category("services").add("notification", notificationService);
