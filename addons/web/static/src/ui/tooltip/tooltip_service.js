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
         * @type {string | null}
         */
        let suppressedTitle = null;
        /**
         * @type {string | null}
         */
        let previousDescribedBy = null;
        let isDescribing = false;
        let nextTooltipId = 1;
        const elementsWithTooltips = new WeakMap();

        function describeTarget(/** @type {string} */ tooltipId) {
            previousDescribedBy = target.getAttribute("aria-describedby");
            isDescribing = true;
            target.setAttribute(
                "aria-describedby",
                previousDescribedBy ? `${previousDescribedBy} ${tooltipId}` : tooltipId,
            );
        }

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

        function startWatchingTarget() {
            stopWatchingTarget();
            unwatchTarget = watchForDetachedTarget(target, cleanup);
        }

        function stopWatchingTarget() {
            unwatchTarget?.();
            unwatchTarget = null;
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
         * @param {HTMLElement} el
         */
        function openElementsTooltip(el) {
            if (el.nodeType === Node.TEXT_NODE) {
                return;
            }
            const element = /** @type {HTMLElement | null} */ (
                el.closest("[data-tooltip], [data-tooltip-template]")
            );
            if (target && (target === el || target === element)) {
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
                    } catch {}
                }
                if (dataset.tooltipDelay) {
                    params.delay = Number.parseInt(dataset.tooltipDelay, 10);
                }
                openTooltip(element, /** @type {any} */ (params));
            }
        }

        /**
         * @param {MouseEvent} ev
         */
        function onMouseenter(ev) {
            openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
        }

        /**
         * @param {FocusEvent} ev
         */
        function onFocusin(ev) {
            openElementsTooltip(/** @type {HTMLElement} */ (ev.target));
        }

        /**
         * @param {HTMLElement} el
         * @returns {boolean}
         */
        function isTapToShow(el) {
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
        function onClick(ev) {
            const el = /** @type {HTMLElement} */ (ev.target);
            if (isHelpNode(el)) {
                ev.preventDefault();
            }
            if (!target || (hasTouch() && isTapToShow(el))) {
                return;
            }
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
         * @param {TouchEvent} ev
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
         * @param {TouchEvent} ev
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
            if (holder && !holder.dataset.tooltipTouchTapToShow) {
                browser.clearTimeout(showTimer);
                if (openTooltipTimeout) {
                    cleanup();
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
                cleanup();
                for (const dispose of listenerDisposers) {
                    dispose();
                }
                listenerDisposers.length = 0;
            },
        };
    },
};

registry.category("services").add("tooltip", tooltipService);
