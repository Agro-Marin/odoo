// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet */

import { Component, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { router, routerBus } from "@web/core/browser/router";
import { RouterEvent } from "@web/core/events";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { getViewportDimensions, useViewportChange } from "@web/core/utils/dom/dvu";
import { compensateScrollbar } from "@web/core/utils/dom/scrolling";
import { clamp } from "@web/core/utils/format/numbers";
import { useBus, useForwardRefToParent } from "@web/core/utils/hooks";
import { useThrottleForAnimation } from "@web/core/utils/timing";
import { useActiveElement } from "@web/ui/ui_service";

const DISMISS_ANIMATION_FALLBACK_DELAY = 1000;

/**
 * The `@keyframes` the sheet is animated by, declared in `bottom_sheet.scss`.
 * Renaming one there without renaming it here costs the slide-out its end event
 * and the sheet closes on `DISMISS_ANIMATION_FALLBACK_DELAY` instead.
 */
const SLIDE_IN_ANIMATION = "bottom-sheet-in";
const SLIDE_OUT_ANIMATION = "bottom-sheet-out";

/**
 * Runs `callback` the first time the named animation on `sheetEl` ITSELF
 * reaches one of `types`.
 *
 * Both filters carry weight. Without the target check a descendant's animation
 * ends the sheet's. Without the name check the two animations the sheet plays
 * are indistinguishable: `.o_bottom_sheet_dismissing` overrides
 * `.o_bottom_sheet_ready` at equal specificity, so raising it swaps
 * `animation-name` on the element that is still running the slide-in, and the
 * browser fires `animationcancel` for the slide-in right there. A listener
 * watching for "the slide-out finished" accepted that cancellation, so a sheet
 * dismissed inside its 400ms opening animation vanished with no slide-out at
 * all -- verified in Chrome, which emits
 * `animationstart:in, animationcancel:in, animationstart:out, animationend:out`.
 *
 * @param {HTMLElement} sheetEl
 * @param {string} animationName
 * @param {(keyof HTMLElementEventMap & ("animationend" | "animationcancel"))[]} types
 * @param {() => void} callback
 * @returns {() => void}
 */
function onSheetAnimation(sheetEl, animationName, types, callback) {
    const dispose = () => {
        for (const type of types) {
            sheetEl.removeEventListener(type, handler);
        }
    };
    const handler = (/** @type {AnimationEvent} */ ev) => {
        if (ev.target === sheetEl && ev.animationName === animationName) {
            dispose();
            callback();
        }
    };
    for (const type of types) {
        sheetEl.addEventListener(type, handler);
    }
    return dispose;
}

export class BottomSheet extends Component {
    static template = "web.BottomSheet";

    static defaultProps = {
        class: "",
        closeOnClickAway: () => true,
        closeOnEscape: true,
        componentProps: {},
        setActiveElement: true,
    };

    static props = {
        component: { optional: true, type: Function },
        componentProps: { optional: true, type: Object },
        close: { type: Function },
        target: { optional: true },

        class: { optional: true },
        id: { optional: true, type: String },
        role: { optional: true, type: String },

        closeOnClickAway: { optional: true, type: Function },
        closeOnEscape: { optional: true, type: Boolean },
        onBack: { optional: true, type: Function },
        preventDismissOnContentScroll: { optional: true, type: Boolean },
        setActiveElement: { optional: true, type: Boolean },

        ref: { optional: true, type: Function },
        slots: { optional: true, type: Object },
    };

    historyMarker = {};
    /**
     * What the hosted component asked to close WITH. The sheet cannot forward
     * it inline the way `web.Popover` hands over `props.close` untouched: it
     * has to intercept the call to play the slide-out first, and every other
     * way in -- the handle button, Escape, the backdrop, a popped history
     * entry -- is an event handler whose own argument must never be mistaken
     * for a close parameter. So `close` records and `slideOut` forwards.
     * @type {any}
     */
    closeParams = undefined;
    /** @type {(() => void)[]} */
    animationCleanups = [];
    /** @type {boolean} */
    prefersReducedMotion = false;

    setup() {
        this.maxHeightPercent = 90;

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
            initialHeight: 0,
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

        if (this.props.closeOnEscape) {
            useHotkey("escape", () => this.slideOut());
        }

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
            // `animationend` only: a cancelled slide-in means the sheet is on
            // its way out, and `slideOut` has just turned snapping off.
            this.animationCleanups.push(
                onSheetAnimation(
                    this.sheetRef.el,
                    SLIDE_IN_ANIMATION,
                    ["animationend"],
                    () => {
                        this.state.isSnappingEnabled = true;
                    },
                ),
            );
        }
    }

    updateDimensions() {
        const rail = this.scrollRailRef.el;
        rail.style.setProperty("scroll-snap-type", "none", "important");

        // How far open the sheet is, before the measurement that gives that
        // fraction a new denominator.
        const previousDismissHeight = this.measurements.initialHeight;
        const openRatio = previousDismissHeight
            ? rail.scrollTop / previousDismissHeight
            : 1;

        this.measureDimensions();
        this.applyDimensions();

        // Re-anchor. The rail's scrollable extent IS the dismiss area, and it
        // just changed size, so a preserved raw offset leaves the sheet
        // part-dragged against the new one -- and anything under
        // `dismissThreshold` reads as the drag-to-dismiss gesture, which is how
        // dismissing the keyboard came to close the sheet.
        rail.scrollTop = clamp(openRatio, 0, 1) * this.measurements.initialHeight;

        this.updateProgressValue(rail.scrollTop);

        rail.style.removeProperty("scroll-snap-type");
    }

    measureDimensions() {
        const viewportHeight = getViewportDimensions().height;
        const maxHeightPx = (this.maxHeightPercent / 100) * viewportHeight;

        // Every constraint the PREVIOUS measurement wrote has to come off, or
        // the sheet is re-derived from the size it is already pinned at.
        // `min-height: var(--sheet-height)` was already handled; its mirror
        // `max-height: var(--sheet-max-height)` was not, so once a virtual
        // keyboard shrank the viewport the natural height was capped at the
        // shrunken value and the sheet could never grow back.
        const sheet = this.sheetRef.el;
        sheet.style.setProperty("min-height", "0", "important");
        sheet.style.setProperty("max-height", "none", "important");
        sheet.style.setProperty("height", "auto", "important");
        const naturalHeight = sheet.offsetHeight;
        sheet.style.removeProperty("min-height");
        sheet.style.removeProperty("max-height");
        sheet.style.removeProperty("height");
        const initialHeightPx = Math.min(naturalHeight, maxHeightPx);

        this.measurements = {
            viewportHeight,
            naturalHeight,
            initialHeight: initialHeightPx,
            maxHeight: maxHeightPx,
            dismissThreshold: Math.min(initialHeightPx * 0.3, 100),
        };
    }

    applyDimensions() {
        const rail = this.scrollRailRef.el;
        const { initialHeight, viewportHeight } = this.measurements;

        // Every dimension in px off the one viewport this component measures.
        // `--sheet-height` used to be a ratio of the VISUAL viewport emitted in
        // `dvh`, which is the LAYOUT viewport: the two part company as soon as a
        // virtual keyboard is up, and the backend's viewport meta leaves
        // `interactive-widget` at its default, so they do. The sheet then got a
        // `min-height` larger than the `max-height` meant to cap it -- and
        // min-height wins -- rendering it far taller than the visible area.
        this.containerRef.el?.style.setProperty(
            "--sheet-viewport-height",
            `${viewportHeight}px`,
        );
        rail.style.setProperty("--sheet-height", `${initialHeight || 0}px`);
        rail.style.setProperty("--sheet-max-height", `${viewportHeight}px`);
        rail.style.setProperty("--dismiss-height", `${initialHeight || 0}px`);
    }

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

    setupEventHandlers() {
        const scrollRail = this.scrollRailRef.el;
        scrollRail.addEventListener("scroll", this.throttledOnScroll);
        this.animationCleanups.push(() =>
            scrollRail.removeEventListener("scroll", this.throttledOnScroll),
        );
    }

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
     * @param {number} scrollTop
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

    slideOut() {
        if (this.state.isDismissing) {
            return;
        }

        if (this.prefersReducedMotion || !this.sheetRef.el) {
            this.props.close?.(this.closeParams);
        } else {
            let closed = false;
            const onAnimationDone = () => {
                if (closed) {
                    return;
                }
                closed = true;
                browser.clearTimeout(fallbackTimer);
                dispose();
                this.props.close?.(this.closeParams);
            };
            // `animationcancel` counts here: whatever cut the slide-out short,
            // the sheet is going away and the caller is owed its close.
            const dispose = onSheetAnimation(
                this.sheetRef.el,
                SLIDE_OUT_ANIMATION,
                ["animationend", "animationcancel"],
                onAnimationDone,
            );
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

    /** @param {any} [closeParams] */
    close(closeParams) {
        this.closeParams = closeParams;
        this.slideOut();
    }

    /**
     * @param {PointerEvent} ev
     */
    onBackdropClick(ev) {
        if (this.props.closeOnClickAway(/** @type {any} */ (ev.target))) {
            this.slideOut();
        }
    }

    back() {
        if (this.props.onBack) {
            this.props.onBack();
        } else {
            this.slideOut();
        }
    }
}
