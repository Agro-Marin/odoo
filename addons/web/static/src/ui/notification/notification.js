// @ts-check
/** @odoo-module native */

/** @module @web/ui/notification/notification */

import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";

const AUTOCLOSE_DELAY = 4000;

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
    remainingDelay = 0;
    /**
     * Number of reasons the countdown is currently held: the pointer being
     * over the notification and the focus being inside it are independent, so
     * releasing one must not resume the countdown while the other still holds.
     */
    holds = 0;

    setup() {
        this.rootRef = useRef("root");
        this.autocloseProgress = useRef("autoclose_progress_bar");
        this.remainingDelay = this.props.autocloseDelay;
        onMounted(() => this.startNotificationTimer());
        onWillUnmount(() => this.stopNotificationTimer());
    }

    /**
     * @returns {boolean}
     */
    get isAssertive() {
        return ["danger", "warning"].includes(this.props.type);
    }

    /**
     * @param {Node | null} [relatedTarget]
     * @returns {boolean}
     */
    isInternalTransition(relatedTarget) {
        return (
            relatedTarget instanceof Node &&
            Boolean(this.rootRef.el?.contains(relatedTarget))
        );
    }

    /** @param {FocusEvent | MouseEvent} [ev] */
    freeze(ev) {
        if (this.isInternalTransition(/** @type {Node | null} */ (ev?.relatedTarget))) {
            return;
        }
        this.holds++;
        if (this.props.sticky || !this.closeTimeout || this.holds > 1) {
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

    /** @param {FocusEvent | MouseEvent} [ev] */
    refresh(ev) {
        if (this.isInternalTransition(/** @type {Node | null} */ (ev?.relatedTarget))) {
            return;
        }
        this.holds = Math.max(0, this.holds - 1);
        if (this.holds > 0) {
            return;
        }
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
