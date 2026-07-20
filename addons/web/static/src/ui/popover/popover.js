// @ts-check
/** @odoo-module native */

/** @module @web/ui/popover/popover - Positioned popover component with click-away close, hotkey escape, and arrow rendering */

import { Component, onMounted, onWillDestroy, useRef } from "@odoo/owl";
import { usePosition } from "@web/core/position/position_hook";
import { reverseForRTL } from "@web/core/position/utils";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { useForwardRefToParent } from "@web/core/utils/hooks";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";
import { useActiveElement } from "@web/ui/block/ui_service";
import { OVERLAY_SYMBOL } from "@web/ui/overlay/overlay_container";

/**
 * @param {EventTarget} target
 * @param {string} eventName
 * @param {(ev: Event) => any} handler
 * @param {AddEventListenerOptions} [eventParams]
 */
function useEarlyExternalListener(target, eventName, handler, eventParams) {
    target.addEventListener(eventName, handler, eventParams);
    onWillDestroy(() => target.removeEventListener(eventName, handler, eventParams));
}

/**
 * Trigger the callback with the clicked element when the window is clicked,
 * including from within an iframe. Iframes are (re-)scanned whenever focus
 * moves into one, so iframes added after the popover opened (dashboards,
 * html field editors) and iframe reloads are covered too.
 *
 * @param {Popover} popover
 * @param {(node?: Node) => any} callback
 */
function useClickAway(popover, callback) {
    /** @type {(() => void)[]} */
    const iframeDisposers = [];
    /**
     * Windows whose pointerdown listener is currently attached. Keyed by
     * Window (not iframe element): a reload swaps the iframe's Window and
     * drops the old listener with it, so the new one must be re-armed.
     * @type {WeakSet<Window>}
     */
    const armedWindows = new WeakSet();

    function armIframe(/** @type {HTMLIFrameElement} */ iframeEl) {
        const win = iframeEl.contentWindow;
        if (!win || armedWindows.has(win)) {
            return;
        }
        const handler = () => {
            const popupEl = popover.popoverRef.el;
            let checkEl = iframeEl.parentElement;
            while (checkEl) {
                if (checkEl === popupEl) {
                    // Ignore iframes within popup
                    return;
                }
                checkEl = checkEl.parentElement;
            }
            callback(iframeEl);
        };
        try {
            win.addEventListener("pointerdown", handler, { capture: true });
            armedWindows.add(win);
            iframeDisposers.push(() =>
                win.removeEventListener("pointerdown", handler, { capture: true }),
            );
        } catch (e) {
            // In some browsers, if an iframe is loaded from a different
            // domain accessing it results in a SecurityError.
            if (e.name !== "SecurityError") {
                throw e;
            }
        }
    }

    function scanIframes() {
        for (const iframeEl of document.querySelectorAll("iframe")) {
            armIframe(/** @type {HTMLIFrameElement} */ (iframeEl));
        }
    }

    function blurHandler(/** @type {Event} */ ev) {
        const target =
            /** @type {FocusEvent} */ (ev).relatedTarget || document.activeElement;
        if (/** @type {Element} */ (target)?.tagName === "IFRAME") {
            scanIframes();
            return callback(/** @type {Node} */ (target));
        }
    }

    function navigationHandler() {
        callback(document.documentElement);
    }

    function pointerDownHandler(/** @type {Event} */ ev) {
        callback(/** @type {Node} */ (ev.composedPath()[0]));
    }

    useEarlyExternalListener(window, "pointerdown", pointerDownHandler, {
        capture: true,
    });
    useEarlyExternalListener(window, "blur", blurHandler, { capture: true });
    useEarlyExternalListener(window, "popstate", navigationHandler, {
        capture: true,
    });
    scanIframes();
    onWillDestroy(() => {
        for (const dispose of iframeDisposers) {
            dispose();
        }
    });
}

const POPOVERS = new WeakMap();
/**
 * Can be used to retrieve the popover element for a given target.
 * @param {HTMLElement} target
 * @returns {HTMLElement | undefined} the popover element if it exists
 */
export function getPopoverForTarget(target) {
    return POPOVERS.get(target);
}

/**
 * Generic popover component with auto-positioning, click-away closing,
 * arrow rendering, opening animation, and optional fixed position.
 */
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
    };
    static props = {
        // Main props
        component: { type: Function },
        componentProps: { optional: true, type: Object },
        target: {
            validate: (/** @type {any} */ target) => {
                // target may be inside an iframe, so get the Element constructor
                // to test against from its owner document's default view
                const Element = target?.ownerDocument?.defaultView?.Element;
                return (
                    (Boolean(Element) &&
                        (target instanceof Element ||
                            target instanceof window.Element)) ||
                    (typeof target === "object" &&
                        target?.constructor?.name?.endsWith("Element"))
                );
            },
        },
        close: { type: Function },

        // Styling and semantical props
        animation: { optional: true, type: Boolean },
        arrow: { optional: true, type: Boolean },
        class: { optional: true },
        role: { optional: true, type: String },

        // Positioning props
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

        // Control props
        closeOnClickAway: { optional: true, type: Function },
        closeOnEscape: { optional: true, type: Boolean },
        setActiveElement: { optional: true, type: Boolean },

        // Technical props
        ref: { optional: true, type: Function },
        slots: { optional: true, type: Object },
    };
    static animationTime = 200;

    setup() {
        if (this.props.setActiveElement) {
            useActiveElement("ref");
        }

        useForwardRefToParent("ref");
        this.popoverRef = useRef("ref");
        this.position = usePosition(
            "ref",
            () => this.props.target,
            this.positioningOptions,
        );

        if (!this.props.animation) {
            this.animationDone = true;
        }

        const resizeObserver = new ResizeObserver(() => {
            if (!this.props.fixedPosition && this.animationDone) {
                this.position.unlock();
            }
        });

        onMounted(() => {
            POPOVERS.set(this.props.target, this.popoverRef.el);
            resizeObserver.observe(this.popoverRef.el);
        });
        onWillDestroy(() => {
            // Only clear the mapping if it still points at OUR element: when two
            // popovers share a target, the second's onMounted overwrote the
            // entry, so an unconditional delete on the first's teardown would
            // wipe the second's live mapping (getPopoverForTarget would then
            // return undefined while the popover is still open).
            if (POPOVERS.get(this.props.target) === this.popoverRef.el) {
                POPOVERS.delete(this.props.target);
            }
            resizeObserver.disconnect();
        });

        if (this.props.target.isConnected) {
            useClickAway(this, this.onClickAway.bind(this));

            if (this.props.closeOnEscape) {
                useHotkey("escape", () => this.props.close());
            }
            const targetObserver = new MutationObserver(this.onTargetMutate.bind(this));
            // Observe the target's parent for child-list changes so the popover
            // closes once its target is detached. Fall back to the root node
            // when the parent is not an element (ShadowRoot/Document), whose
            // `parentElement` is null. Deliberately NOT `subtree: true`:
            // observing the whole document fires onTargetMutate on every
            // unrelated mutation and transiently closes popovers whose target
            // is re-rendered in place by Owl (e.g. the properties definition
            // popover, whose dropdowns then never populate).
            const observedNode =
                this.props.target.parentElement || this.props.target.getRootNode();
            targetObserver.observe(observedNode, { childList: true });
            onWillDestroy(() => targetObserver.disconnect());
        } else {
            this.props.close();
        }
    }

    /** @returns {Object} merged CSS class object for the popover root element */
    get defaultClassObj() {
        return mergeClasses(
            "o_popover popover mw-100 bs-popover-auto",
            this.props.class,
        );
    }

    /** @returns {Object} options passed to `usePosition` */
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
     * Play the opening slide+fade animation.
     * @param {string} direction - "top" | "right" | "bottom" | "left"
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
            /** @type {any} */ (this.constructor).animationTime,
        );
    }

    /**
     * @param {EventTarget} target
     * @returns {boolean} whether target is inside the popover or its trigger
     */
    isInside(target) {
        return (
            this.props.target?.contains(target) ||
            this.popoverRef?.el?.contains(/** @type {Node} */ (target)) ||
            /** @type {any} */ (this.env)[OVERLAY_SYMBOL]?.contains(target)
        );
    }

    /** @param {Node} target - the click target to test for click-away */
    onClickAway(target) {
        if (this.props.closeOnClickAway(target) && !this.isInside(target)) {
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

        // opening animation (only once)
        if (this.props.animation && !this.animationDone) {
            this.position.lock();
            this.animate(direction).finished.then(
                () => {
                    this.animationDone = true;
                    if (!this.props.fixedPosition) {
                        this.position.unlock();
                    }
                },
                () => {
                    // Animation cancelled (popover closed mid-animation) — ignore
                },
            );
        }

        if (this.props.fixedPosition) {
            // Prevent further positioning updates if fixed position is wanted
            this.position.lock();
        }
    }

    /** Close popover if target element was removed from the DOM. */
    onTargetMutate() {
        if (!this.props.target.isConnected) {
            this.props.close();
        }
    }

    /**
     * Update arrow position and CSS based on positioning solution.
     * @param {string} direction - "top" | "right" | "bottom" | "left"
     * @param {string} variant - "start" | "middle" | "end" | "fit"
     * @param {number} variantOffset
     */
    updateArrow(direction, variant, variantOffset) {
        const { el } = this.popoverRef;

        // Reverse the direction if RTL as bootstrap expects it that way
        [direction, variant] = reverseForRTL(
            /** @type {any} */ (direction),
            /** @type {any} */ (variant),
        );

        // Update the bootstrap popper placement, to give the arrow its shape
        el.dataset.popperPlacement = direction;

        // Update arrow position
        const vertical = ["top", "bottom"].includes(direction);
        const placementProperty = vertical ? "left" : "top";
        const placement = {
            start: "--position-min",
            middle: "--position-center",
            fit: "--position-center",
            end: "--position-max",
        }[variant];
        const arrowEl = /** @type {HTMLElement} */ (
            el.querySelector(":scope > .popover-arrow")
        );
        Object.assign(arrowEl.style, {
            top: "",
            left: "",
            [placementProperty]: `clamp(
                var(--position-min),
                calc(var(${placement}) - ${variantOffset}px),
                var(--position-max)
            )`,
        });

        // Should the arrow get sucked?
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
