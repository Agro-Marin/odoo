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
     * Why the countdown is currently held. The pointer being over the
     * notification and the focus being inside it are independent, so releasing
     * one must not resume while the other still holds.
     *
     * Named reasons rather than a count, so that a release is idempotent: a
     * reason that was never added deletes to a no-op, and one added twice does
     * not need two releases. Counting instead made every release cancel
     * whichever hold happened to be outstanding, which needed a "was anything
     * held at all" guard that still could not tell WHICH source was being
     * released.
     *
     * Chrome does pair these events, including the awkward case -- a
     * notification appearing under a stationary pointer gets no mouseenter, but
     * then gets no mouseleave either, and if focus arrives first Chrome
     * re-hit-tests and delivers the missing mouseenter before it. So this is
     * robustness against synthetic and non-Chrome event streams, not a fix for
     * an observed Chrome defect.
     * @type {Set<"hover" | "focus">}
     */
    holds = new Set();

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

    /**
     * @param {"hover" | "focus"} reason
     * @param {boolean} held
     * @param {FocusEvent | MouseEvent} [ev]
     */
    setHold(reason, held, ev) {
        if (this.isInternalTransition(/** @type {Node | null} */ (ev?.relatedTarget))) {
            return;
        }
        const wasHeld = this.holds.size > 0;
        if (held) {
            this.holds.add(reason);
        } else {
            this.holds.delete(reason);
        }
        const isHeld = this.holds.size > 0;
        if (isHeld === wasHeld) {
            return;
        }
        if (held) {
            this.pauseNotificationTimer();
        } else if (this.remainingDelay > 0) {
            this.startNotificationTimer();
        }
    }

    pauseNotificationTimer() {
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
