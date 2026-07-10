// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification - Individual notification toast with auto-close progress bar and action buttons */

import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

const AUTOCLOSE_DELAY = 4000;

/**
 * Individual notification toast with auto-close progress bar.
 *
 * Supports warning/danger/success/info types, sticky mode,
 * configurable autoclose delay, and action buttons.
 */
export class Notification extends Component {
    static template = "web.NotificationWowl";
    static props = {
        message: {
            validate: (/** @type {unknown} */ m) =>
                typeof m === "string" ||
                (typeof m === "object" && typeof m.toString === "function"),
        },
        type: {
            type: String,
            optional: true,
            validate: (/** @type {any} */ t) =>
                ["warning", "danger", "success", "info"].includes(t),
        },
        title: {
            type: [String, Boolean, { toString: Function }],
            optional: true,
        },
        className: { type: String, optional: true },
        buttons: {
            type: Array,
            element: {
                type: Object,
                shape: {
                    name: { type: String },
                    icon: { type: String, optional: true },
                    primary: { type: Boolean, optional: true },
                    onClick: Function,
                },
            },
            optional: true,
        },
        sticky: { type: Boolean, optional: true },
        autocloseDelay: { type: Number, optional: true },
        close: { type: Function },
    };
    static defaultProps = {
        buttons:
            /** @type {{ name: string, icon?: string, primary?: boolean, onClick: Function }[]} */ ([]),
        className: "",
        type: "warning",
        autocloseDelay: AUTOCLOSE_DELAY,
    };
    setup() {
        this.autocloseProgress = useRef("autoclose_progress_bar");
        onMounted(() => this.startNotificationTimer());
        onWillUnmount(() => this.stopNotificationTimer());
    }

    /** Pause the auto-close timer (e.g. on mouse hover). */
    freeze() {
        this.stopNotificationTimer();
    }

    /** Restart the auto-close timer from the beginning. */
    refresh() {
        this.startNotificationTimer();
    }

    close() {
        this.props.close();
    }

    startNotificationTimer() {
        if (this.props.sticky) {
            return;
        }
        this.stopNotificationTimer();
        // The close deadline stays a browser.setTimeout (mockable time); the
        // shrinking progress bar is a compositor-driven CSS animation instead
        // of a per-frame JS width write.
        this._closeTimeout = browser.setTimeout(
            () => this.close(),
            this.props.autocloseDelay,
        );
        const progressEl = this.autocloseProgress.el;
        if (progressEl) {
            // Clearing the animation and forcing a reflow restarts it from 100%
            // on refresh().
            progressEl.style.animation = "none";
            void progressEl.offsetWidth;
            progressEl.style.animation = `o-notification-progress ${this.props.autocloseDelay}ms linear forwards`;
        }
    }

    stopNotificationTimer() {
        if (this._closeTimeout) {
            browser.clearTimeout(this._closeTimeout);
            this._closeTimeout = null;
        }
        if (this.autocloseProgress.el) {
            // Without the animation the bar falls back to its 0-width default,
            // matching the previous freeze() behavior of emptying the bar.
            this.autocloseProgress.el.style.animation = "none";
        }
    }
}
