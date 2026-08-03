// @ts-check
/** @odoo-module native */

/** @module @web/ui/tooltip/tooltip_service */

import { whenReady } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { watchForDetachedTarget } from "@web/ui/popover/detached_target_watcher";
import { Tooltip } from "@web/ui/tooltip/tooltip";

export const OPEN_DELAY = 400;
export const SHOW_AFTER_DELAY = 250;

let nextTooltipId = 1;

/**
 * The one tooltip the service is currently tracking: the element it belongs to,
 * everything borrowed from that element, and everything scheduled against it.
 *
 * One object rather than seven parallel `let`s, so "nothing is being tracked"
 * is a single state instead of seven that a hand-written `cleanup` has to reset
 * together, in the right order, on every exit path.
 */
export class TrackedTooltip {
    /**
     * @param {HTMLElement} el
     * @param {() => void} onDetached
     */
    constructor(el, onDetached) {
        this.el = el;
        /** @type {number | null} */
        this.openTimeout = null;
        /** @type {(() => void) | null} */
        this.closePopover = null;
        /** @type {string | null} */
        this.borrowedDescribedBy = null;
        this.isDescribing = false;

        this.borrowedTitle = el.getAttribute("title");
        if (this.borrowedTitle !== null) {
            // Held, not shared: the native tooltip would otherwise show
            // alongside ours.
            el.removeAttribute("title");
        }
        this.unwatch = watchForDetachedTarget(el, onDetached);
    }

    /** @returns {string} the id the tooltip element must carry */
    describe() {
        const tooltipId = `o_tooltip_${nextTooltipId++}`;
        this.borrowedDescribedBy = this.el.getAttribute("aria-describedby");
        this.isDescribing = true;
        this.el.setAttribute(
            "aria-describedby",
            this.borrowedDescribedBy
                ? `${this.borrowedDescribedBy} ${tooltipId}`
                : tooltipId,
        );
        return tooltipId;
    }

    /**
     * Gives back everything borrowed and cancels everything scheduled. Safe to
     * call more than once.
     */
    release() {
        if (this.borrowedTitle !== null) {
            this.el.setAttribute("title", this.borrowedTitle);
            this.borrowedTitle = null;
        }
        if (this.isDescribing) {
            if (this.borrowedDescribedBy === null) {
                this.el.removeAttribute("aria-describedby");
            } else {
                this.el.setAttribute("aria-describedby", this.borrowedDescribedBy);
            }
            this.borrowedDescribedBy = null;
            this.isDescribing = false;
        }
        this.unwatch?.();
        this.unwatch = null;
        browser.clearTimeout(this.openTimeout);
        this.openTimeout = null;
        // Nulled before the call: closing the popover re-enters the service's
        // `onClose`, which must not see this tooltip as still tracked.
        const closePopover = this.closePopover;
        this.closePopover = null;
        closePopover?.();
    }
}

/**
 * The `tooltip` service.
 *
 * A class rather than a closure returning an object literal; see
 * `core/hotkeys/hotkey_service.js` for the reasoning and
 * `tooling/architecture/js_service_shape.py` for the budget.
 *
 * As in `hotkey_service`, the body listeners are registered as arrow wrappers
 * calling `this.<handler>(ev)` rather than as bare method references. Passing
 * the method itself would bind the pre-patch function into `addEventListener`,
 * so a later `patch(TooltipService.prototype, { onMouseenter() {…} })` would
 * never be reached — the seam defeated by its own setup. The wrapper keeps one
 * stable reference for `removeEventListener` while resolving the handler
 * through the prototype on every event.
 */
export class TooltipService {
    /**
     * @param {{ popover: any }} services
     */
    constructor({ popover }) {
        this.popover = popover;
        /** @type {TrackedTooltip | null} */
        this.tracked = null;
        /** @type {number} */
        this.showTimer = undefined;
        this.elementsWithTooltips = new WeakMap();
        /** @type {(() => void)[]} */
        this.listenerDisposers = [];
        this.destroyed = false;

        whenReady(() => {
            if (this.destroyed) {
                return;
            }
            if (hasTouch()) {
                this.addBodyListener("touchstart", (ev) => this.onTouchStart(ev));
                this.addBodyListener("touchend", (ev) => this.onTouchEnd(ev));
                this.addBodyListener("touchcancel", (ev) => this.onTouchEnd(ev));
            }

            this.addBodyListener("mouseenter", (ev) => this.onMouseenter(ev), {
                capture: true,
            });
            this.addBodyListener("mouseleave", (ev) => this.cleanupTooltip(ev), {
                capture: true,
            });
            this.addBodyListener("focusin", (ev) => this.onFocusin(ev), {
                capture: true,
            });
            this.addBodyListener("focusout", (ev) => this.cleanupTooltip(ev), {
                capture: true,
            });
            this.addBodyListener("click", (ev) => this.onClick(ev), { capture: true });
        });
    }

    /**
     * @param {HTMLElement} el
     * @return {boolean}
     */
    isHelpNode(el) {
        return (
            el.textContent === "?" &&
            (el.hasAttribute("data-tooltip") ||
                el.hasAttribute("data-tooltip-template"))
        );
    }

    cleanup() {
        // Detached before released, so the re-entrant `onClose` that closing
        // the popover triggers sees no tracked tooltip and stops there.
        const released = this.tracked;
        this.tracked = null;
        released?.release();
        browser.clearTimeout(this.showTimer);
    }

    /**
     * @param {HTMLElement} el
     * @param {object} param1
     * @param {string} [param1.tooltip]
     * @param {string} [param1.template]
     * @param {object} [param1.info]
     * @param {'top'|'bottom'|'left'|'right'} param1.position
     * @param {number} [param1.delay]
     */
    openTooltip(el, { tooltip = "", template, info, position, delay = OPEN_DELAY }) {
        this.cleanup();
        if (!tooltip && !template) {
            return;
        }

        const opening = new TrackedTooltip(el, () => this.cleanup());
        this.tracked = opening;
        const timeoutDelay = this.isHelpNode(el) ? 0 : delay;
        opening.openTimeout = browser.setTimeout(() => {
            opening.openTimeout = null;
            if (!el.isConnected) {
                return;
            }
            opening.closePopover = this.popover.add(
                el,
                Tooltip,
                { tooltip, template, info, id: opening.describe() },
                {
                    position,
                    onClose: () => {
                        if (this.tracked === opening) {
                            opening.closePopover = null;
                            this.cleanup();
                        }
                    },
                },
            );
        }, timeoutDelay);
    }

    /**
     * @param {HTMLElement} el
     */
    openElementsTooltip(el) {
        if (el.nodeType === Node.TEXT_NODE) {
            return;
        }
        const element = /** @type {HTMLElement | null} */ (
            el.closest("[data-tooltip], [data-tooltip-template]")
        );
        if (this.tracked && (this.tracked.el === el || this.tracked.el === element)) {
            return;
        }
        if (this.elementsWithTooltips.has(el)) {
            this.openTooltip(el, this.elementsWithTooltips.get(el));
        } else if (element) {
            const dataset = element.dataset;
            /** @type {Record<string, any>} */
            const params = {
                tooltip: dataset.tooltip,
                template: dataset.tooltipTemplate,
                position: dataset.tooltipPosition,
            };
            if (dataset.tooltipInfo) {
                try {
                    params.info = JSON.parse(dataset.tooltipInfo);
                } catch {}
            }
            if (dataset.tooltipDelay) {
                // A hand-authored attribute, so a typo is a real outcome:
                // `parseInt` answers NaN for one and `setTimeout(NaN)`
                // fires on the next tick, which turned a malformed delay
                // into an INSTANT tooltip rather than the default one. A
                // negative value lands the same way.
                const delay = Number.parseInt(dataset.tooltipDelay, 10);
                if (Number.isFinite(delay) && delay >= 0) {
                    params.delay = delay;
                }
            }
            this.openTooltip(element, /** @type {any} */ (params));
        }
    }

    /**
     * @param {MouseEvent} ev
     */
    onMouseenter(ev) {
        this.openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
    }

    /**
     * @param {FocusEvent} ev
     */
    onFocusin(ev) {
        this.openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
    }

    /**
     * @param {HTMLElement} el
     * @returns {boolean}
     */
    isTapToShow(el) {
        if (!hasTouch()) {
            return false;
        }
        const holder = /** @type {HTMLElement | null} */ (
            el.closest?.("[data-tooltip], [data-tooltip-template]")
        );
        return Boolean(holder?.dataset.tooltipTouchTapToShow);
    }

    /**
     * @param {MouseEvent} ev
     */
    onClick(ev) {
        const el = /** @type {HTMLElement} */ (ev.target);
        if (this.isHelpNode(el)) {
            ev.preventDefault();
        }
        if (!this.tracked || this.isTapToShow(el)) {
            return;
        }
        if (this.tracked.el.contains(el) || this.tracked.openTimeout) {
            this.cleanup();
        }
    }

    cleanupTooltip(/** @type {Event} */ ev) {
        if (this.tracked?.el === ev.target) {
            this.cleanup();
        }
    }
    /**
     * @param {TouchEvent} ev
     */
    onTouchStart(ev) {
        this.cleanup();
        const el = /** @type {HTMLElement} */ (ev.target);
        const timeoutDelay = this.isHelpNode(el) ? 0 : SHOW_AFTER_DELAY;
        this.showTimer = browser.setTimeout(() => {
            this.openElementsTooltip(el);
        }, timeoutDelay);
    }

    /**
     * @param {TouchEvent} ev
     */
    onTouchEnd(ev) {
        const el = /** @type {HTMLElement} */ (ev.target);
        if (this.isHelpNode(el)) {
            ev.preventDefault();
            return;
        }
        const holder = /** @type {HTMLElement | null} */ (
            el.closest("[data-tooltip], [data-tooltip-template]")
        );
        if (holder && !holder.dataset.tooltipTouchTapToShow) {
            browser.clearTimeout(this.showTimer);
            if (this.tracked?.openTimeout) {
                this.cleanup();
            }
        }
    }

    /**
     * @param {string} type
     * @param {(ev: any) => void} handler
     * @param {AddEventListenerOptions} [options]
     */
    addBodyListener(type, handler, options) {
        document.body.addEventListener(type, handler, options);
        this.listenerDisposers.push(() =>
            document.body.removeEventListener(type, handler, options),
        );
    }

    /**
     * @param {HTMLElement} el
     * @param {Record<string, any>} params
     * @returns {() => void}
     */
    add(el, params) {
        this.elementsWithTooltips.set(el, params);
        return () => {
            this.elementsWithTooltips.delete(el);
            if (this.tracked?.el === el) {
                this.cleanup();
            }
        };
    }

    destroy() {
        this.destroyed = true;
        this.cleanup();
        for (const dispose of this.listenerDisposers) {
            dispose();
        }
        this.listenerDisposers.length = 0;
    }
}

export const tooltipService = {
    dependencies: ["popover"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ popover: any }} services
     * @returns {TooltipService}
     */
    start(env, services) {
        return new TooltipService(services);
    },
};

registry.category("services").add("tooltip", tooltipService);
