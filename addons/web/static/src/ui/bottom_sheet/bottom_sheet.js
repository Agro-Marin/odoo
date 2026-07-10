// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet - Mobile-friendly slide-up panel with drag-to-dismiss and snap points */

import { Component, onMounted, useExternalListener, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getViewportDimensions, useViewportChange } from "@web/core/utils/dom/dvu";
import { compensateScrollbar } from "@web/core/utils/dom/scrolling";
import { clamp } from "@web/core/utils/format/numbers";
import { useForwardRefToParent } from "@web/core/utils/hooks";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";

export class BottomSheet extends Component {
    static template = "web.BottomSheet";

    static defaultProps = {
        class: "",
    };

    static props = {
        // Main props
        component: { type: Function },
        componentProps: { optional: true, type: Object },
        close: { type: Function },

        class: { optional: true },
        role: { optional: true, type: String },

        // Behavior props
        onBack: { optional: true, type: Function },
        preventDismissOnContentScroll: { optional: true, type: Boolean },

        // Technical props
        ref: { optional: true, type: Function },
        slots: { optional: true, type: Object },
    };

    setup() {
        this.maxHeightPercent = 90;

        this.state = useState({
            isPositionedReady: false, // Sheet is ready for display
            isSnappingEnabled: false,
            isDismissing: false, // Sheet is being dismissed
            progress: 0, // Visual progress (0-1)
        });

        // Measurements and configuration
        this.measurements = {
            viewportHeight: 0,
            naturalHeight: 0,
            maxHeight: 0,
            dismissThreshold: 0,
        };

        // Popover Ref Requirement
        useForwardRefToParent("ref");

        // References
        this.containerRef = useRef("container");
        this.scrollRailRef = useRef("scrollRail");
        this.sheetRef = useRef("sheet");
        this.sheetBodyRef = useRef("ref");

        this.throttledOnScroll = useThrottleForAnimation(this.onScroll.bind(this));

        // Adapt dimensions when mobile virtual-keyboards or browsers bars toggle
        useViewportChange(() => {
            if (this.state.isPositionedReady && !this.state.isDismissing) {
                this.updateDimensions();
            }
        });

        useHotkey("escape", () => this.slideOut());

        // Intercept the mobile "back" gesture/button: push a history state on open,
        // then on popstate push another state and close (traps back-navigation).
        // TODO: this history entry leaks when the sheet is closed by other means
        // than "back" (it is never popped), leaving a stale entry on the stack.
        browser.history.pushState({ bottomSheet: true }, "");
        this.handlePopState = () => {
            if (this.state.isPositionedReady && !this.state.isDismissing) {
                browser.history.pushState({ bottomSheet: true }, "");
                this.slideOut();
            }
        };
        useExternalListener(window, "popstate", this.handlePopState);

        onMounted(() => {
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
        // Set up event handlers only after sizing/positioning is complete.
        this.setupEventHandlers();
        this.state.isPositionedReady = true;

        if (this.prefersReducedMotion) {
            this.state.isSnappingEnabled = true;
        } else {
            this.sheetRef.el?.addEventListener(
                "animationend",
                () => (this.state.isSnappingEnabled = true),
                {
                    once: true,
                },
            );
            this.sheetRef.el?.addEventListener(
                "animationcancel",
                () => (this.state.isSnappingEnabled = true),
                {
                    once: true,
                },
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

        // Reset any previously set constraints to measure natural height
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
        const initialPosition = this.measurements.naturalHeight;
        const progress = clamp(scrollTop / initialPosition, 0, 1);

        if (Math.abs(this.state.progress - progress) > 0.01) {
            this.state.progress = progress;
        }
    }

    /**
     * Initiates the slide out animation and dismissal
     */
    slideOut() {
        // Prevent duplicate calls
        if (this.state.isDismissing) {
            return;
        }

        if (this.prefersReducedMotion) {
            this.props.close?.();
        } else {
            // Close only once, whichever of the two events fires first.
            const onAnimationDone = () => {
                this.sheetRef.el?.removeEventListener("animationend", onAnimationDone);
                this.sheetRef.el?.removeEventListener(
                    "animationcancel",
                    onAnimationDone,
                );
                this.props.close?.();
            };
            this.sheetRef.el?.addEventListener("animationend", onAnimationDone, {
                once: true,
            });
            this.sheetRef.el?.addEventListener("animationcancel", onAnimationDone, {
                once: true,
            });
        }

        // Update state to trigger animation
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
