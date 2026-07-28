// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet - Mobile-friendly slide-up panel with drag-to-dismiss and snap points */

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { RouterEvent } from "@web/core/events";
import { getViewportDimensions, useViewportChange } from "@web/core/utils/dom/dvu";
import { compensateScrollbar } from "@web/core/utils/dom/scrolling";
import { clamp } from "@web/core/utils/format/numbers";
import { useBus, useForwardRefToParent } from "@web/core/utils/hooks";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";
import { useActiveElement } from "@web/ui/ui_service";

/**
 * Delay before giving up on the dismiss animation events. Safely above
 * `$o_BottomSheet_slideOut_duration` (bottom_sheet.variables.scss); if neither
 * `animationend` nor `animationcancel` fired by then (detached sheet element,
 * animation removed by a theme), close anyway instead of soft-locking the
 * sheet behind `isDismissing`.
 */
const DISMISS_ANIMATION_FALLBACK_DELAY = 1000;

/**
 * Run `callback` once the sheet element finishes (or aborts) an animation of
 * ITS OWN. `animationend` bubbles, so a descendant ending an animation — a
 * spinner, a menu entry, anything the hosted component animates — would
 * otherwise be mistaken for the sheet's slide and cut it short: snapping would
 * engage before the slide-in landed, and a dismissal would close the sheet
 * before the slide-out played.
 *
 * @param {HTMLElement} sheetEl
 * @param {() => void} callback
 * @returns {() => void} disposer, also called automatically once `callback` ran
 */
function onSheetAnimationEnd(sheetEl, callback) {
    const dispose = () => {
        sheetEl.removeEventListener("animationend", handler);
        sheetEl.removeEventListener("animationcancel", handler);
    };
    const handler = (/** @type {AnimationEvent} */ ev) => {
        if (ev.target === sheetEl) {
            dispose();
            callback();
        }
    };
    sheetEl.addEventListener("animationend", handler);
    sheetEl.addEventListener("animationcancel", handler);
    return dispose;
}

export class BottomSheet extends Component {
    static template = "web.BottomSheet";

    static defaultProps = {
        class: "",
        componentProps: {},
        setActiveElement: true,
    };

    static props = {
        /**
         * Optional: the template renders the `default` slot instead when no
         * component is given. Requiring it made that branch — and with it the
         * `slots`, `onBack` and `back()` API below — unreachable: prop
         * validation rejected every slot-only sheet before it could render.
         */
        component: { optional: true, type: Function },
        componentProps: { optional: true, type: Object },
        close: { type: Function },
        /** The element the sheet was opened from; only used to scope the overlay. */
        target: { optional: true },

        class: { optional: true },
        role: { optional: true, type: String },

        closeOnClickAway: { optional: true, type: [Boolean, Function] },
        onBack: { optional: true, type: Function },
        preventDismissOnContentScroll: { optional: true, type: Boolean },
        setActiveElement: { optional: true, type: Boolean },

        ref: { optional: true, type: Function },
        slots: { optional: true, type: Object },
    };

    /** Identity token for this sheet's ephemeral history entry. */
    historyMarker = {};
    /** @type {(() => void)[]} */
    animationCleanups = [];
    /** @type {boolean} */
    prefersReducedMotion = false;

    setup() {
        this.maxHeightPercent = 90;

        /**
         * Bound once, not per render: these go out as props/slot values, and a
         * fresh closure on every render would re-render the hosted component
         * on each scroll frame (`state.progress` ticks continuously).
         */
        this.close = this.close.bind(this);
        this.back = this.back.bind(this);

        if (this.props.setActiveElement) {
            useActiveElement("ref");
        }

        this.state = useState({
            isPositionedReady: false,
            isSnappingEnabled: false,
            isDismissing: false,
            progress: 0,
        });

        this.measurements = {
            viewportHeight: 0,
            naturalHeight: 0,
            maxHeight: 0,
            dismissThreshold: 0,
        };

        useForwardRefToParent("ref");

        this.containerRef = useRef("container");
        this.scrollRailRef = useRef("scrollRail");
        this.sheetRef = useRef("sheet");
        this.sheetBodyRef = useRef("ref");

        this.throttledOnScroll = useThrottleForAnimation(this.onScroll.bind(this));

        useViewportChange(() => {
            if (this.state.isPositionedReady && !this.state.isDismissing) {
                this.updateDimensions();
            }
        });

        useHotkey("escape", () => this.slideOut());

        useBus(routerBus, RouterEvent.EPHEMERAL_POPPED, ({ detail }) => {
            if (
                detail.markers.includes(this.historyMarker) &&
                this.state.isPositionedReady &&
                !this.state.isDismissing
            ) {
                this.slideOut();
            }
        });
        onWillUnmount(() => {
            for (const cleanup of this.animationCleanups.splice(0)) {
                cleanup();
            }
            router.releaseEphemeral(this.historyMarker);
        });

        onMounted(() => {
            router.pushEphemeral(this.historyMarker);

            const isReduced =
                browser.matchMedia(`(prefers-reduced-motion: reduce)`).matches === true;

            this.prefersReducedMotion =
                isReduced ||
                getComputedStyle(this.containerRef.el).animationName === "none";

            this.initializeSheet();
            compensateScrollbar(this.scrollRailRef.el, true, true, "padding-right");
        });
    }

    /** Sets up measurements, dimensions, position, and event handlers for the sheet. */
    initializeSheet() {
        if (!this.containerRef.el || !this.scrollRailRef.el || !this.sheetRef.el) {
            return;
        }

        this.measureDimensions();
        this.applyDimensions();
        this.positionSheet();
        this.setupEventHandlers();
        this.state.isPositionedReady = true;

        if (this.prefersReducedMotion) {
            this.state.isSnappingEnabled = true;
        } else {
            this.animationCleanups.push(
                onSheetAnimationEnd(this.sheetRef.el, () => {
                    this.state.isSnappingEnabled = true;
                }),
            );
        }
    }

    /** Recalculates dimensions on viewport change, preserving extended state. */
    updateDimensions() {
        this.state.isSnappingEnabled = false;

        this.measureDimensions();
        this.applyDimensions();

        const scrollTop = this.scrollRailRef.el.scrollTop;
        this.updateProgressValue(scrollTop);

        this.state.isSnappingEnabled = true;
    }

    /** Measures viewport/sheet dimensions, including natural height. */
    measureDimensions() {
        const viewportHeight = getViewportDimensions().height;
        const maxHeightPx = (this.maxHeightPercent / 100) * viewportHeight;

        const sheet = this.sheetRef.el;
        sheet.style.removeProperty("min-height");
        sheet.style.removeProperty("height");

        const naturalHeight = sheet.offsetHeight;
        const initialHeightPx = Math.min(naturalHeight, maxHeightPx);

        this.measurements = {
            viewportHeight,
            naturalHeight,
            initialHeight: initialHeightPx,
            maxHeight: maxHeightPx,
            dismissThreshold: Math.min(initialHeightPx * 0.3, 100),
        };
    }

    /** Sets CSS custom properties (heights) on the scroll rail from current measurements. */
    applyDimensions() {
        const rail = this.scrollRailRef.el;

        const heightPercent = Math.min(
            (this.measurements.initialHeight / this.measurements.viewportHeight) * 100,
            this.maxHeightPercent,
        );

        rail.style.setProperty("--sheet-height", `${heightPercent}dvh`);
        rail.style.setProperty(
            "--sheet-max-height",
            `${this.measurements.viewportHeight}px`,
        );
        rail.style.setProperty(
            "--dismiss-height",
            `${this.measurements.initialHeight || 0}px`,
        );
    }

    /** Sets initial scroll position and content overflow behavior. */
    positionSheet() {
        const scrollRail = this.scrollRailRef.el;
        const bodyContent = this.sheetBodyRef.el;

        const scrollValue = this.measurements.maxHeight;

        if (bodyContent) {
            bodyContent.style.overflowY = "auto";
        }

        scrollRail.scrollTop = scrollValue || 0;
        scrollRail.style.containerType = "scroll-state size";
    }

    /** Registers the scroll listener on the rail. */
    setupEventHandlers() {
        const scrollRail = this.scrollRailRef.el;
        scrollRail.addEventListener("scroll", this.throttledOnScroll);
    }

    /** Updates progress and dismisses the sheet once scroll falls below the threshold. */
    onScroll() {
        if (!this.scrollRailRef.el) {
            return;
        }

        const scrollTop = this.scrollRailRef.el.scrollTop;
        this.updateProgressValue(scrollTop);

        if (scrollTop < this.measurements.dismissThreshold) {
            this.slideOut();
        }
    }

    /**
     * @param {number} scrollTop - Current scroll position
     */
    updateProgressValue(scrollTop) {
        const { naturalHeight } = this.measurements;
        if (!naturalHeight) {
            return;
        }
        const progress = clamp(scrollTop / naturalHeight, 0, 1);

        if (Math.abs(this.state.progress - progress) > 0.01) {
            this.state.progress = progress;
        }
    }

    /**
     * Initiates the slide out animation and dismissal
     */
    slideOut() {
        if (this.state.isDismissing) {
            return;
        }

        if (this.prefersReducedMotion || !this.sheetRef.el) {
            this.props.close?.();
        } else {
            let closed = false;
            const onAnimationDone = () => {
                if (closed) {
                    return;
                }
                closed = true;
                browser.clearTimeout(fallbackTimer);
                dispose();
                this.props.close?.();
            };
            const dispose = onSheetAnimationEnd(this.sheetRef.el, onAnimationDone);
            const fallbackTimer = browser.setTimeout(
                onAnimationDone,
                DISMISS_ANIMATION_FALLBACK_DELAY,
            );
            this.animationCleanups.push(() => {
                browser.clearTimeout(fallbackTimer);
                dispose();
            });
        }

        this.state.isDismissing = true;
        this.state.isSnappingEnabled = false;
    }

    /**
     * Closes the sheet (public API)
     */
    close() {
        this.slideOut();
    }

    /**
     * Backdrop tap. Honours `closeOnClickAway` so a caller that vetoes
     * click-away closing (a dropdown whose menu owns a nested overlay) behaves
     * the same whether it was routed to a popover or to a sheet.
     *
     * @param {PointerEvent} ev
     */
    onBackdropClick(ev) {
        const { closeOnClickAway } = this.props;
        const allowed =
            typeof closeOnClickAway === "function"
                ? closeOnClickAway(/** @type {any} */ (ev.target))
                : (closeOnClickAway ?? true);
        if (allowed) {
            this.slideOut();
        }
    }

    /**
     * Handles back button press (public API)
     */
    back() {
        if (this.props.onBack) {
            this.props.onBack();
        } else {
            this.slideOut();
        }
    }
}
