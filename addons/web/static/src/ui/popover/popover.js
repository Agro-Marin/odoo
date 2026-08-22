// @ts-check
/** @odoo-module native */

import { Component, onMounted, onWillDestroy, useRef } from "@odoo/owl";
import { prefersReducedMotion } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { usePosition } from "@web/core/position/position_hook";
import { reverseForRTL } from "@web/core/position/utils";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { useClickAway } from "@web/core/utils/dom/click_away";
import { useForwardRefToParent } from "@web/core/utils/hooks";
import { OVERLAY_SYMBOL } from "@web/ui/overlay/overlay_container";
import { PRESENTED_PROPS } from "@web/ui/overlay/presenter";
import { watchForDetachedTarget } from "@web/ui/popover/detached_target_watcher";
import { useActiveElement } from "@web/ui/ui_service";

const POPOVERS = new WeakMap();
/**
 * @param {HTMLElement} target
 * @returns {HTMLElement | undefined}
 */
export function getPopoverForTarget(target) {
    return POPOVERS.get(target);
}

export class Popover extends Component {
    static template = "web.Popover";
    static defaultProps = {
        animation: true,
        arrow: true,
        class: "",
        closeOnClickAway: () => true,
        closeOnEscape: true,
        componentProps: {},
        fixedPosition: false,
        position: "bottom",
        setActiveElement: true,
    };
    static props = {
        ...PRESENTED_PROPS,
        component: { type: Function },
        target: {
            validate: (/** @type {any} */ target) =>
                target?.nodeType === Node.ELEMENT_NODE,
        },

        animation: { optional: true, type: Boolean },
        arrow: { optional: true, type: Boolean },

        fixedPosition: { optional: true, type: Boolean },
        extendedFlipping: { optional: true, type: Boolean },
        holdOnHover: { optional: true, type: Boolean },
        onPositioned: { optional: true, type: Function },
        position: {
            optional: true,
            type: String,
            validate: (/** @type {string} */ p) => {
                const [d, v = "middle"] = p.split("-");
                return (
                    ["top", "bottom", "left", "right"].includes(d) &&
                    ["start", "middle", "end", "fit"].includes(v)
                );
            },
        },
    };
    static animationTime = 200;

    isHovered = false;
    positionLocked = false;
    animationDone = false;
    hasTarget = true;

    setup() {
        if (this.props.setActiveElement) {
            useActiveElement("ref");
        }

        useForwardRefToParent("ref");
        this.popoverRef = useRef("ref");
        this.arrowRef = useRef("arrow");
        this.position = usePosition(
            "ref",
            () => this.props.target,
            this.positioningOptions,
        );

        if (!this.props.animation) {
            this.animationDone = true;
        }

        const resizeObserver = new ResizeObserver(() => this.onResized());

        onMounted(() => {
            POPOVERS.set(this.props.target, this.popoverRef.el);
            resizeObserver.observe(this.popoverRef.el);
        });
        onWillDestroy(() => {
            if (POPOVERS.get(this.props.target) === this.popoverRef.el) {
                POPOVERS.delete(this.props.target);
            }
            resizeObserver.disconnect();
        });

        if (this.props.target.isConnected) {
            useClickAway(this.onClickAway.bind(this), {
                getAnchor: () => this.props.target,
                getContentEl: () => this.popoverRef.el,
            });

            if (this.props.closeOnEscape) {
                useHotkey("escape", () => this.props.close());
            }
            const unwatch = watchForDetachedTarget(this.props.target, () =>
                this.props.close(),
            );
            onWillDestroy(unwatch);
        } else {
            this.hasTarget = false;
            this.props.close();
        }
    }

    /** @returns {Object} */
    get defaultClassObj() {
        return mergeClasses(
            "o_popover popover mw-100 bs-popover-auto",
            this.props.class,
        );
    }

    /** @returns {Object} */
    get positioningOptions() {
        return {
            extendedFlipping: this.props.extendedFlipping,
            margin: this.props.arrow ? 8 : 0,
            onPositioned: (
                /** @type {HTMLElement} */ el,
                /** @type {any} */ solution,
            ) => {
                this.onPositioned(solution);
                this.props.onPositioned?.(el, solution);
            },
            position: this.props.position,
            shrink: true,
        };
    }

    /**
     * @param {string} direction
     * @returns {Animation}
     */
    animate(direction) {
        const transform = {
            top: ["translateY(-5%)", "translateY(0)"],
            right: ["translateX(5%)", "translateX(0)"],
            bottom: ["translateY(5%)", "translateY(0)"],
            left: ["translateX(-5%)", "translateX(0)"],
        }[direction];
        return this.popoverRef.el.animate(
            { opacity: [0, 1], transform },
            prefersReducedMotion()
                ? 0
                : /** @type {any} */ (this.constructor).animationTime,
        );
    }

    /**
     * @param {EventTarget} target
     * @returns {boolean}
     */
    isInside(target) {
        return (
            this.props.target?.contains(target) ||
            this.popoverRef?.el?.contains(/** @type {Node} */ (target)) ||
            /** @type {any} */ (this.env)[OVERLAY_SYMBOL]?.contains(target)
        );
    }

    /**
     * @returns {boolean}
     */
    get isPositionFrozen() {
        return Boolean(
            this.props.fixedPosition ||
            (this.props.holdOnHover && this.isHovered) ||
            !this.animationDone,
        );
    }

    reposition() {
        this.positionLocked = false;
        this.position.unlock();
    }

    /**
     * @param {boolean} locked
     */
    setPositionLocked(locked) {
        if (locked) {
            this.positionLocked = true;
            this.position.lock();
        } else {
            this.reposition();
        }
    }

    syncPositionLock() {
        if (this.isPositionFrozen !== this.positionLocked) {
            this.setPositionLocked(this.isPositionFrozen);
        }
    }

    onResized() {
        if (!this.isPositionFrozen) {
            this.reposition();
        }
    }

    onPointerEnter() {
        this.isHovered = true;
        this.syncPositionLock();
    }

    onPointerLeave() {
        this.isHovered = false;
        this.syncPositionLock();
    }

    /** @param {Node} target */
    onClickAway(target) {
        if (!this.isInside(target) && this.props.closeOnClickAway(target)) {
            this.props.close();
        }
    }

    onPositioned(
        /** @type {{ direction: any, variant: any, variantOffset: any }} */ {
            direction,
            variant,
            variantOffset,
        },
    ) {
        if (this.props.arrow) {
            this.updateArrow(direction, variant, variantOffset);
        }

        const startsAnimation = this.props.animation && !this.animationDone;
        this.syncPositionLock();
        if (startsAnimation) {
            this.animate(direction).finished.then(
                () => {
                    this.animationDone = true;
                    this.syncPositionLock();
                },
                () => {},
            );
        }
    }

    /**
     * @param {string} direction
     * @param {string} variant
     * @param {number} variantOffset
     */
    updateArrow(direction, variant, variantOffset) {
        const { el } = this.popoverRef;

        [direction, variant] = reverseForRTL(
            /** @type {any} */ (direction),
            /** @type {any} */ (variant),
        );

        el.dataset.popperPlacement = direction;

        const vertical = ["top", "bottom"].includes(direction);
        const placementProperty = vertical ? "left" : "top";
        const placement = {
            start: "--position-min",
            middle: "--position-center",
            fit: "--position-center",
            end: "--position-max",
        }[variant];
        const arrowEl = /** @type {HTMLElement} */ (this.arrowRef.el);
        if (!arrowEl) {
            return;
        }
        Object.assign(arrowEl.style, {
            top: "",
            left: "",
            [placementProperty]: `clamp(
                var(--position-min),
                calc(var(${placement}) - ${variantOffset}px),
                var(--position-max)
            )`,
        });

        const sizeProperty = vertical ? "width" : "height";
        const { [sizeProperty]: arrowSize, [placementProperty]: arrowPosition } =
            arrowEl.getBoundingClientRect();
        const { [sizeProperty]: targetSize, [placementProperty]: targetPosition } =
            this.props.target.getBoundingClientRect();
        const arrowCenter = arrowPosition + arrowSize / 2;
        const margin = arrowSize / 2 - 1;
        const hasEnoughSpace = arrowSize < targetSize - 2 * margin;
        const isOutsideSafeEdge =
            arrowCenter < targetPosition + margin ||
            arrowCenter > targetPosition + targetSize - margin;
        arrowEl.classList.toggle("sucked", hasEnoughSpace && isOutsideSafeEdge);
    }
}
