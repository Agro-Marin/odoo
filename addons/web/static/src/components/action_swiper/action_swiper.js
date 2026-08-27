// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onWillUnmount,
    status,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { reportUncaught } from "@web/core/errors/error_utils";
import { localization } from "@web/core/l10n/localization";
import { Deferred } from "@web/core/utils/concurrency";
import { clamp } from "@web/core/utils/format/numbers";
const BOUNCE_ACTION_DELAY = 500;
const FORWARDS_ACTION_DELAY = 100;
const FORWARDS_RESET_DELAY = 100;
const SCROLL_LOCK_THRESHOLD = 40;

/**
 * @param {HTMLElement[]} scrollables
 * @param {"left" | "right"} direction
 * @returns {boolean}
 */
const isScrollSwipable = (scrollables, direction) => {
    if (direction === "left") {
        return !scrollables.some((e) => e.scrollLeft !== 0);
    }
    return !scrollables.some(
        (e) =>
            e.scrollLeft + Math.round(e.getBoundingClientRect().width) !==
            e.scrollWidth,
    );
};

export class ActionSwiper extends Component {
    static template = "web.ActionSwiper";
    static props = {
        onLeftSwipe: {
            type: Object,
            shape: {
                action: Function,
                icon: { type: String, optional: true },
                bgColor: { type: String, optional: true },
            },
            optional: true,
        },
        onRightSwipe: {
            type: Object,
            shape: {
                action: Function,
                icon: { type: String, optional: true },
                bgColor: { type: String, optional: true },
            },
            optional: true,
        },
        slots: Object,
        animationOnMove: { type: Boolean, optional: true },
        animationType: { type: String, optional: true },
        swipeDistanceRatio: { type: Number, optional: true },
        swipeInvalid: { type: Function, optional: true },
    };

    static defaultProps = {
        onLeftSwipe: undefined,
        onRightSwipe: undefined,
        animationOnMove: true,
        animationType: "bounce",
        swipeDistanceRatio: 2,
    };

    setup() {
        this.actionTimeoutId = null;
        this.resetTimeoutId = null;
        this.defaultState = {
            containerStyle: "",
            isSwiping: false,
            width: undefined,
        };
        this.targetContainer = useRef("targetContainer");
        this.state = useState({ ...this.defaultState });
        this.scrollables = undefined;
        this.startX = undefined;
        this.swipedDistance = 0;
        this.isScrollValidated = false;
        onMounted(() => {
            if (this.targetContainer.el) {
                this.state.width =
                    this.targetContainer.el.getBoundingClientRect().width;
            }
        });
        onWillUnmount(() => {
            browser.clearTimeout(this.actionTimeoutId);
            browser.clearTimeout(this.resetTimeoutId);
        });
    }
    get localizedProps() {
        return {
            onLeftSwipe:
                localization.direction === "rtl"
                    ? this.props.onRightSwipe
                    : this.props.onLeftSwipe,
            onRightSwipe:
                localization.direction === "rtl"
                    ? this.props.onLeftSwipe
                    : this.props.onRightSwipe,
        };
    }

    onTouchCancel() {
        if (this.state.isSwiping) {
            this.reset();
        }
    }

    onTouchEnd() {
        if (this.state.isSwiping) {
            this.state.isSwiping = false;
            if (
                this.localizedProps.onRightSwipe &&
                this.swipedDistance > this.state.width / this.props.swipeDistanceRatio
            ) {
                this.swipedDistance = this.state.width;
                this.handleSwipe(this.localizedProps.onRightSwipe.action);
            } else if (
                this.localizedProps.onLeftSwipe &&
                this.swipedDistance < -this.state.width / this.props.swipeDistanceRatio
            ) {
                this.swipedDistance = -this.state.width;
                this.handleSwipe(this.localizedProps.onLeftSwipe.action);
            } else {
                this.state.containerStyle = "";
            }
        }
    }
    /**
     * @param {TouchEvent} ev
     */
    onTouchMove(ev) {
        if (this.state.isSwiping) {
            if (this.props.swipeInvalid && this.props.swipeInvalid()) {
                this.state.isSwiping = false;
                return;
            }
            const { onLeftSwipe, onRightSwipe } = this.localizedProps;
            this.swipedDistance = clamp(
                ev.touches[0].clientX - this.startX,
                onLeftSwipe ? -this.state.width : 0,
                onRightSwipe ? this.state.width : 0,
            );
            if (Math.abs(this.swipedDistance) > SCROLL_LOCK_THRESHOLD) {
                ev.preventDefault();
            }
            if (
                !this.isScrollValidated &&
                this.scrollables &&
                !isScrollSwipable(
                    this.scrollables,
                    this.swipedDistance > 0 ? "left" : "right",
                )
            ) {
                this.reset();
                return;
            }
            this.isScrollValidated = true;

            if (this.props.animationOnMove) {
                this.state.containerStyle = `transform: translateX(${this.swipedDistance}px)`;
            }
        }
    }
    /**
     * @param {TouchEvent} ev
     */
    onTouchStart(ev) {
        this.scrollables = /** @type {HTMLElement[]} */ (
            ev.composedPath().filter((e) => {
                const el = /** @type {HTMLElement} */ (e);
                return (
                    el.nodeType === 1 &&
                    this.targetContainer.el.contains(el) &&
                    el.scrollWidth > el.getBoundingClientRect().width &&
                    ["auto", "scroll"].includes(
                        window.getComputedStyle(el)["overflow-x"],
                    )
                );
            })
        );
        if (!this.state.width) {
            this.state.width =
                this.targetContainer.el &&
                this.targetContainer.el.getBoundingClientRect().width;
        }
        this.state.isSwiping = true;
        this.isScrollValidated = false;
        this.startX = ev.touches[0].clientX;
    }

    reset() {
        Object.assign(this.state, { ...this.defaultState });
        this.scrollables = undefined;
        this.startX = undefined;
        this.swipedDistance = 0;
        this.isScrollValidated = false;
    }

    /**
     * @param {any} error
     */
    reportActionError(error) {
        reportUncaught(error);
    }

    handleSwipe(action) {
        browser.clearTimeout(this.actionTimeoutId);
        browser.clearTimeout(this.resetTimeoutId);
        if (this.props.animationType === "bounce") {
            this.state.containerStyle = `transform: translateX(${this.swipedDistance}px)`;
            this.actionTimeoutId = browser.setTimeout(async () => {
                try {
                    await action(Promise.resolve());
                } catch (error) {
                    this.reportActionError(error);
                }
                if (status(this) === "destroyed") {
                    return;
                }
                this.reset();
            }, BOUNCE_ACTION_DELAY);
        } else if (this.props.animationType === "forwards") {
            this.state.containerStyle = `transform: translateX(${this.swipedDistance}px)`;
            this.actionTimeoutId = browser.setTimeout(async () => {
                const prom = new Deferred();
                try {
                    await action(prom);
                } catch (error) {
                    this.reportActionError(error);
                }
                if (status(this) === "destroyed") {
                    prom.resolve();
                    return;
                }
                this.state.isSwiping = true;
                this.state.containerStyle = `transform: translateX(${-this.swipedDistance}px)`;
                this.resetTimeoutId = browser.setTimeout(() => {
                    prom.resolve();
                    this.reset();
                }, FORWARDS_RESET_DELAY);
            }, FORWARDS_ACTION_DELAY);
        } else {
            return action(Promise.resolve());
        }
    }
}
