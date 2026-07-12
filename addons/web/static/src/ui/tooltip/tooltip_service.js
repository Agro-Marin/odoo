// @ts-check
/** @odoo-module native */

/** @module @web/ui/tooltip/tooltip_service - Service for data-tooltip attribute-driven tooltips with hover/touch support */

import { whenReady } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { Tooltip } from "@web/ui/tooltip/tooltip";

/**
 * The tooltip service allows to display custom tooltips on every elements with
 * a "data-tooltip" attribute. This attribute can be set on elements for which
 * we prefer a custom tooltip instead of the native one displaying the value of
 * the "title" attribute.
 *
 * Usage:
 *   <button data-tooltip="This is a tooltip">Do something</button>
 *
 * The ideal position of the tooltip can be specified thanks to the attribute
 * "data-tooltip-position":
 *   <button data-tooltip="This is a tooltip" data-tooltip-position="left">Do something</button>
 *
 * The opening delay can be modified with the "data-tooltip-delay" attribute (default: 400):
 *   <button data-tooltip="This is a tooltip" data-tooltip-delay="0">Do something</button>
 *
 * The default behaviour on touch devices to open the tooltip can be modified from "hold-to-show"
 * to "tap-to-show" "with the data-tooltip-touch-tap-to-show" attribute:
 *  <button data-tooltip="This is a tooltip" data-tooltip-touch-tap-to-show="true">Do something</button>
 *
 * For advanced tooltips containing dynamic and/or html content, the
 * "data-tooltip-template" and "data-tooltip-info" attributes can be used.
 * For example, let's suppose the following qweb template:
 *   <t t-name="some_template">
 *     <ul>
 *       <li>info.x</li>
 *       <li>info.y</li>
 *     </ul>
 *   </t>
 * This template can then be used in a tooltip as follows:
 *   <button data-tooltip-template="some_template" data-tooltip-info="info">Do something</button>
 * with "info" being a stringified object with two keys "x" and "y".
 */

export const OPEN_DELAY = 400;
export const CLOSE_DELAY = 200;
export const SHOW_AFTER_DELAY = 250;

export const tooltipService = {
    dependencies: ["popover"],
    /**
     * @param {import("@web/env").OdooEnv} env
     * @param {{ popover: any }} services
     */
    start(env, { popover }) {
        /** @type {number | null} */
        let openTooltipTimeout;
        /** @type {(() => void) | null} */
        let closeTooltip;
        /** @type {number} */
        let showTimer;
        /** @type {HTMLElement | null} */
        let target = null;
        const elementsWithTooltips = new WeakMap();

        /**
         * Detect if the current node is the `sup` tooltip node
         * @param {HTMLElement} el
         * @return {boolean}
         */
        function isHelpNode(el) {
            return (
                el.textContent === "?" &&
                (el.hasAttribute("data-tooltip") ||
                    el.hasAttribute("data-tooltip-template"))
            );
        }

        /**
         * Closes the currently opened tooltip if any, or prevent it from opening.
         */
        function cleanup() {
            target = null;
            stopCleanupInterval();
            browser.clearTimeout(openTooltipTimeout);
            openTooltipTimeout = null;
            // Also clear the touch pre-delay: rapid touchstarts would
            // otherwise stack multiple pending openElementsTooltip calls.
            browser.clearTimeout(showTimer);
            if (closeTooltip) {
                closeTooltip();
                closeTooltip = null;
            }
        }

        /** @type {number | null} */
        let cleanupIntervalId = null;

        /**
         * While a tooltip is pending or open, regularly check that its target
         * is still in the DOM and close the tooltip otherwise.  The interval
         * only runs during that window (see ``cleanup``): keeping it alive
         * forever would wake the main thread 5 times per second for nothing.
         */
        function startCleanupInterval() {
            if (cleanupIntervalId === null) {
                cleanupIntervalId = browser.setInterval(() => {
                    if (shouldCleanup()) {
                        cleanup();
                    }
                }, CLOSE_DELAY);
            }
        }

        function stopCleanupInterval() {
            if (cleanupIntervalId !== null) {
                browser.clearInterval(cleanupIntervalId);
                cleanupIntervalId = null;
            }
        }

        /**
         * Whether the current target left the DOM and its tooltip should close.
         * @returns {boolean}
         */
        function shouldCleanup() {
            return Boolean(target) && !target.isConnected;
        }

        /**
         * Checks whether there is a tooltip registered on the event target, and
         * if there is, creates a timeout to open the corresponding tooltip
         * after a delay.
         *
         * @param {HTMLElement} el the element on which to add the tooltip
         * @param {object} param1
         * @param {string} [param1.tooltip] the string to add as a tooltip, if
         *  no tooltip template is specified
         * @param {string} [param1.template] the name of the template to use for
         *  tooltip, if any
         * @param {object} [param1.info] info for the tooltip template
         * @param {'top'|'bottom'|'left'|'right'} param1.position
         * @param {number} [param1.delay] delay after which the popover should
         *  open
         */
        function openTooltip(
            el,
            { tooltip = "", template, info, position, delay = OPEN_DELAY },
        ) {
            cleanup();
            if (!tooltip && !template) {
                return;
            }

            target = el;
            startCleanupInterval();
            // Prevent title from showing on a parent at the same time
            target.title = "";
            const timeoutDelay = isHelpNode(el) ? 0 : delay;
            openTooltipTimeout = browser.setTimeout(() => {
                // verify that the element is still in the DOM
                if (target.isConnected) {
                    closeTooltip = popover.add(
                        target,
                        Tooltip,
                        { tooltip, template, info },
                        { position },
                    );
                }
            }, timeoutDelay);
        }

        /**
         * If a tooltip is registered on the element, schedule it to open after a delay.
         * @param {HTMLElement} el
         */
        function openElementsTooltip(el) {
            // Fix weird behavior in Firefox where MouseEvent can be dispatched
            // from TEXT_NODE, even if they shouldn't...
            if (el.nodeType === Node.TEXT_NODE) {
                return;
            }
            const element = /** @type {HTMLElement | null} */ (
                el.closest("[data-tooltip], [data-tooltip-template]")
            );
            if (element && element === target) {
                return;
            }
            if (elementsWithTooltips.has(el)) {
                openTooltip(el, elementsWithTooltips.get(el));
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
                    } catch {
                        // Malformed tooltip data attribute — skip info
                    }
                }
                if (dataset.tooltipDelay) {
                    params.delay = Number.parseInt(dataset.tooltipDelay, 10);
                }
                openTooltip(element, /** @type {any} */ (params));
            }
        }

        /**
         * Schedule opening a tooltip registered on the event target, if any.
         * @param {MouseEvent} ev a "mouseenter" event
         */
        function onMouseenter(ev) {
            openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
        }

        /**
         * Clean up any tooltip registered on the event target.
         * @param {MouseEvent} ev a "click" event
         */
        function onClick(ev) {
            const el = /** @type {HTMLElement} */ (ev.target);
            if (isHelpNode(el)) {
                ev.preventDefault();
            }
            cleanupTooltip(ev);
            if (
                openTooltipTimeout &&
                !closeTooltip &&
                target &&
                !target.contains(/** @type {Node} */ (ev.target))
            ) {
                // A tooltip is pending and the click landed outside its target: cancel
                // it. A real pointer never hits this (mouseleave fires first), but
                // synthetic pointers (tours, tests) skip mouseleave when the hovered
                // element disappears (e.g. a popover this click just closed), which
                // would otherwise let a stale tooltip open after the click.
                cleanup();
            }
        }

        function cleanupTooltip(/** @type {Event} */ ev) {
            if (target == ev.target) {
                cleanup();
            }
        }
        /**
         * Schedule opening a tooltip registered on the event target, if any.
         * @param {TouchEvent} ev a "touchstart" event
         */
        function onTouchStart(ev) {
            cleanup();
            const el = /** @type {HTMLElement} */ (ev.target);
            const timeoutDelay = isHelpNode(el) ? 0 : SHOW_AFTER_DELAY;
            showTimer = browser.setTimeout(() => {
                openElementsTooltip(el);
            }, timeoutDelay);
        }

        /**
         * Cancels a pending tooltip when a touch ends or is cancelled.
         * @param {TouchEvent} ev a "touchend" or "touchcancel" event
         */
        function onTouchEnd(ev) {
            const el = /** @type {HTMLElement} */ (ev.target);
            if (isHelpNode(el)) {
                ev.preventDefault();
                return;
            }
            // Read the tap-to-show flag from the REGISTERED tooltip holder
            // (the ancestor carrying data-tooltip), not the raw touch target:
            // a tap landing on a child element (e.g. an inner <span> or <i>)
            // has no ``tooltipTouchTapToShow`` in its own dataset, so reading
            // from ``el`` silently cancelled the pending tooltip and broke
            // tap-to-show for any tooltip holder with nested content.
            const holder = /** @type {HTMLElement | null} */ (
                el.closest("[data-tooltip], [data-tooltip-template]")
            );
            if (holder) {
                if (!holder.dataset.tooltipTouchTapToShow) {
                    browser.clearTimeout(showTimer);
                    browser.clearTimeout(openTooltipTimeout);
                }
            }
        }

        /** @type {(() => void)[]} */
        const listenerDisposers = [];
        let destroyed = false;

        /**
         * @param {string} type
         * @param {(ev: any) => void} handler
         * @param {AddEventListenerOptions} [options]
         */
        function addBodyListener(type, handler, options) {
            document.body.addEventListener(type, handler, options);
            listenerDisposers.push(() =>
                document.body.removeEventListener(type, handler, options),
            );
        }

        whenReady(() => {
            if (destroyed) {
                return;
            }
            if (hasTouch()) {
                addBodyListener("touchstart", onTouchStart);
                addBodyListener("touchend", onTouchEnd);
                addBodyListener("touchcancel", onTouchEnd);
            }

            // Delegate "mouseenter" to open tooltips
            addBodyListener("mouseenter", onMouseenter, { capture: true });
            // Delegate "mouseleave" to close tooltips
            addBodyListener("mouseleave", cleanupTooltip, { capture: true });
            addBodyListener("click", onClick, { capture: true });
        });

        return {
            add(
                /** @type {HTMLElement} */ el,
                /** @type {Record<string, any>} */ params,
            ) {
                elementsWithTooltips.set(el, params);
                return () => {
                    elementsWithTooltips.delete(el);
                    if (target === el) {
                        cleanup();
                    }
                };
            },
            destroy() {
                destroyed = true;
                stopCleanupInterval();
                browser.clearTimeout(openTooltipTimeout);
                browser.clearTimeout(showTimer);
                // Detach the body listeners: a destroyed service (env
                // teardown in embedded/public contexts) must not keep
                // handling events against a dead popover service.
                for (const dispose of listenerDisposers) {
                    dispose();
                }
                listenerDisposers.length = 0;
            },
        };
    },
};

registry.category("services").add("tooltip", tooltipService);
