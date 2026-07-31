// @ts-check
/** @odoo-module native */

/** @module @web/ui/bottom_sheet/bottom_sheet */

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

const DISMISS_ANIMATION_FALLBACK_DELAY = 1000;

/**
 * @param {HTMLElement} sheetEl
 * @param {() => void} callback
 * @returns {() => void}
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
            this.animationCleanups.push(
                onSheetAnimationEnd(this.sheetRef.el, () => {
                    this.state.isSnappingEnabled = true;
                }),
            );
        }
    }

    updateDimensions() {
        const rail = this.scrollRailRef.el;
        rail.style.setProperty("scroll-snap-type", "none", "important");

        this.measureDimensions();
        this.applyDimensions();
        this.updateProgressValue(rail.scrollTop);

        rail.style.removeProperty("scroll-snap-type");
    }

    measureDimensions() {
        const viewportHeight = getViewportDimensions().height;
        const maxHeightPx = (this.maxHeightPercent / 100) * viewportHeight;

        const sheet = this.sheetRef.el;
        sheet.style.setProperty("min-height", "0", "important");
        sheet.style.setProperty("height", "auto", "important");
        const naturalHeight = sheet.offsetHeight;
        sheet.style.removeProperty("min-height");
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

    close() {
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
