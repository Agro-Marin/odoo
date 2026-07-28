// @ts-check
/** @odoo-module native */

/** @module @web/ui/tooltip/tooltip_service - Service for data-tooltip attribute-driven tooltips with hover/touch support */

import { whenReady } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { watchForDetachedTarget } from "@web/ui/popover/detached_target_watcher";
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
        /**
         * `title` of the current target, suppressed while a custom tooltip is
         * pending or open so the native one does not show alongside it. Screen
         * readers fall back to `title` for the accessible name, so it must be
         * put back on cleanup instead of being destroyed by the first hover.
         * @type {string | null}
         */
        let suppressedTitle = null;
        /**
         * The `aria-describedby` the target carried before the open tooltip
         * appended itself to it, or `null` when we have not touched it. The
         * tooltip is *appended* rather than substituted so an element that
         * already documents itself (a field with its help text) keeps that
         * description while the hover help is up.
         * @type {string | null}
         */
        let previousDescribedBy = null;
        let isDescribing = false;
        let nextTooltipId = 1;
        const elementsWithTooltips = new WeakMap();

        /** Point the target at the tooltip for assistive technology. */
        function describeTarget(/** @type {string} */ tooltipId) {
            previousDescribedBy = target.getAttribute("aria-describedby");
            isDescribing = true;
            target.setAttribute(
                "aria-describedby",
                previousDescribedBy ? `${previousDescribedBy} ${tooltipId}` : tooltipId,
            );
        }

        /** Undo `describeTarget`, leaving any pre-existing description in place. */
        function undescribeTarget() {
            if (!isDescribing) {
                return;
            }
            if (previousDescribedBy === null) {
                target.removeAttribute("aria-describedby");
            } else {
                target.setAttribute("aria-describedby", previousDescribedBy);
            }
            previousDescribedBy = null;
            isDescribing = false;
        }

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
            if (target) {
                if (suppressedTitle !== null) {
                    target.setAttribute("title", suppressedTitle);
                }
                undescribeTarget();
            }
            suppressedTitle = null;
            target = null;
            stopWatchingTarget();
            browser.clearTimeout(openTooltipTimeout);
            openTooltipTimeout = null;
            browser.clearTimeout(showTimer);
            if (closeTooltip) {
                closeTooltip();
                closeTooltip = null;
            }
        }

        /** @type {(() => void) | null} */
        let unwatchTarget = null;

        /**
         * Close the tooltip once its target leaves the DOM.
         *
         * Driven by the shared `MutationObserver` the popover already arms for
         * the very same anchor, not by a timer: the previous 200ms poll woke
         * the main thread 5 times a second for the whole time any tooltip was
         * pending or open — which, on a list of `data-tooltip` cells, is most
         * of the time the pointer is moving — to recompute a fact the observer
         * reports for free and without the up-to-200ms lag.
         */
        function startWatchingTarget() {
            stopWatchingTarget();
            unwatchTarget = watchForDetachedTarget(target, cleanup);
        }

        function stopWatchingTarget() {
            unwatchTarget?.();
            unwatchTarget = null;
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
            startWatchingTarget();
            suppressedTitle = target.getAttribute("title");
            if (suppressedTitle !== null) {
                target.removeAttribute("title");
            }
            const timeoutDelay = isHelpNode(el) ? 0 : delay;
            openTooltipTimeout = browser.setTimeout(() => {
                // Cleared, not left dangling: `onClick` reads this to tell a
                // still-pending tooltip from an open one, and a fired timeout
                // id stays truthy forever.
                openTooltipTimeout = null;
                if (target.isConnected) {
                    const tooltipId = `o_tooltip_${nextTooltipId++}`;
                    describeTarget(tooltipId);
                    closeTooltip = popover.add(
                        target,
                        Tooltip,
                        { tooltip, template, info, id: tooltipId },
                        {
                            position,
                            onClose: () => {
                                if (target === el) {
                                    closeTooltip = null;
                                    cleanup();
                                }
                            },
                        },
                    );
                }
            }, timeoutDelay);
        }

        /**
         * If a tooltip is registered on the element, schedule it to open after a delay.
         * @param {HTMLElement} el
         */
        function openElementsTooltip(el) {
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
         * Schedule opening a tooltip when a tooltipped element receives keyboard
         * focus, so keyboard/screen-reader users get the same help hover exposes
         * (WCAG 1.4.13 — content on hover must also be available on focus).
         * @param {FocusEvent} ev a "focusin" event
         */
        function onFocusin(ev) {
            openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
        }

        /**
         * Whether `el` sits inside a tooltip holder that opted into
         * "tap-to-show". Such a holder deliberately opens its tooltip from the
         * tap itself, so the `click` that ends the tap must not cancel it.
         *
         * @param {HTMLElement} el
         * @returns {boolean}
         */
        function isTapToShow(el) {
            const holder = /** @type {HTMLElement | null} */ (
                el.closest?.("[data-tooltip], [data-tooltip-template]")
            );
            return Boolean(holder?.dataset.tooltipTouchTapToShow);
        }

        /**
         * Close the tooltip of the clicked element, and cancel any tooltip that
         * is still only pending. A click means the user is done reading the
         * hover help, wherever inside the tooltipped element it landed — the
         * previous "outside the target only" test let a click on a *child* of
         * the target (the label inside a button, an icon inside a cell) leave
         * the timeout armed, so the tooltip popped up on top of whatever the
         * click had just triggered.
         *
         * @param {MouseEvent} ev a "click" event
         */
        function onClick(ev) {
            const el = /** @type {HTMLElement} */ (ev.target);
            if (isHelpNode(el)) {
                ev.preventDefault();
            }
            if (!target || isTapToShow(el)) {
                return;
            }
            // `target.contains(el)`, not `target === ev.target`: the click
            // lands on the deepest node, so a button's inner <span> is the
            // common case, and identity left the tooltip up on top of whatever
            // the click had just triggered. A click anywhere else still
            // cancels a tooltip that is only pending, for the same reason.
            if (target.contains(el) || openTooltipTimeout) {
                cleanup();
            }
        }

        function cleanupTooltip(/** @type {Event} */ ev) {
            if (target === ev.target) {
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

            addBodyListener("mouseenter", onMouseenter, { capture: true });
            addBodyListener("mouseleave", cleanupTooltip, { capture: true });
            addBodyListener("focusin", onFocusin, { capture: true });
            addBodyListener("focusout", cleanupTooltip, { capture: true });
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
                stopWatchingTarget();
                browser.clearTimeout(openTooltipTimeout);
                browser.clearTimeout(showTimer);
                for (const dispose of listenerDisposers) {
                    dispose();
                }
                listenerDisposers.length = 0;
            },
        };
    },
};

registry.category("services").add("tooltip", tooltipService);
