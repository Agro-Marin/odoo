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
    /** @type {number | null} */
    closeTimeout = null;
    /** @type {number} */
    timerStart = 0;
    /** Auto-close time left, shrinking across `freeze()`/`refresh()` cycles. */
    remainingDelay = 0;

    setup() {
        this.autocloseProgress = useRef("autoclose_progress_bar");
        this.remainingDelay = this.props.autocloseDelay;
        onMounted(() => this.startNotificationTimer());
        onWillUnmount(() => this.stopNotificationTimer());
    }

    /**
     * Only errors/warnings interrupt a screen reader (role="alert"/assertive);
     * routine success/info toasts announce politely (role="status"/polite) so a
     * "Saved" toast doesn't cut off whatever the user is reading (WCAG 4.1.3).
     * @returns {boolean}
     */
    get isAssertive() {
        return ["danger", "warning"].includes(this.props.type);
    }

    /** Pause the auto-close timer + progress bar in place (e.g. on mouse hover). */
    freeze() {
        if (this.props.sticky || !this.closeTimeout) {
            return;
        }
        const elapsed = browser.performance.now() - this.timerStart;
        this.remainingDelay = Math.max(0, this.remainingDelay - elapsed);
        browser.clearTimeout(this.closeTimeout);
        this.closeTimeout = null;
        if (this.autocloseProgress.el) {
            this.autocloseProgress.el.style.animationPlayState = "paused";
        }
    }

    /**
     * Resume the auto-close timer + progress bar from where `freeze()` paused.
     * A pointer leaving a notification whose timer already fired must not arm
     * a new one: the toast is on its way out.
     */
    refresh() {
        if (this.remainingDelay > 0) {
            this.startNotificationTimer();
        }
    }

    close() {
        this.props.close();
    }

    startNotificationTimer() {
        if (this.props.sticky) {
            return;
        }
        if (this.closeTimeout) {
            browser.clearTimeout(this.closeTimeout);
        }
        this.timerStart = browser.performance.now();
        this.closeTimeout = browser.setTimeout(() => {
            this.remainingDelay = 0;
            this.close();
        }, this.remainingDelay);
        const progressEl = this.autocloseProgress.el;
        if (progressEl) {
            if (progressEl.style.animationPlayState === "paused") {
                progressEl.style.animationPlayState = "running";
            } else {
                progressEl.style.animation = "none";
                void progressEl.offsetWidth;
                progressEl.style.animation = `o-notification-progress ${this.remainingDelay}ms linear forwards`;
                progressEl.style.animationPlayState = "running";
            }
        }
    }

    stopNotificationTimer() {
        if (this.closeTimeout) {
            browser.clearTimeout(this.closeTimeout);
            this.closeTimeout = null;
        }
    }
}
