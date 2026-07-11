// @ts-check
/** @odoo-module native */

/** @module @web/ui/block/ui_service - UI service: viewport size tracking, active element management, block/unblock, and focus trapping */

import { EventBus, reactive, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { getTabableElements, isFocusable } from "@web/core/utils/dom/ui";
import { useService } from "@web/core/utils/hooks";

import { BlockUI } from "./block_ui.js";
export const SIZES = { XS: 0, SM: 1, MD: 2, LG: 3, XL: 4, XXL: 5 };

/**
 * @param {HTMLElement} el
 * @returns {[HTMLElement | undefined, HTMLElement | undefined]} first and last tabable children
 */
export function getFirstAndLastTabableElements(el) {
    const tabableEls = getTabableElements(el);
    return [tabableEls[0], tabableEls.at(-1)];
}

/**
 * Sets the UI active element when the caller component mounts/patches, if
 * the t-reffed element has tabable elements or is itself focusable. Pass a
 * `t-ref` name to delegate to another element than the caller itself.
 *
 * @param {string} refName
 */
export function useActiveElement(refName) {
    if (!refName) {
        throw new Error("refName not given to useActiveElement");
    }
    const uiService = useService("ui");
    const ref = useRef(refName);

    function trapFocus(/** @type {KeyboardEvent} */ e) {
        const hotkey = getActiveHotkey(e);
        if (!["tab", "shift+tab"].includes(hotkey)) {
            return;
        }
        const el = /** @type {HTMLElement} */ (e.currentTarget);
        const [firstTabableEl, lastTabableEl] = getFirstAndLastTabableElements(el);
        if (!firstTabableEl && !lastTabableEl) {
            e.preventDefault();
            e.stopPropagation();
            return;
        }
        switch (hotkey) {
            case "tab":
                if (document.activeElement === lastTabableEl) {
                    firstTabableEl.focus();
                    e.preventDefault();
                    e.stopPropagation();
                }
                break;
            case "shift+tab":
                if (document.activeElement === firstTabableEl) {
                    lastTabableEl.focus();
                    e.preventDefault();
                    e.stopPropagation();
                }
                break;
        }
    }

    useEffect(
        (el) => {
            if (el) {
                const [firstTabableEl] = getFirstAndLastTabableElements(el);
                if (!firstTabableEl && !isFocusable(el)) {
                    // no tabable elements: no need to trap focus nor become the UI active element
                    return;
                }
                const oldActiveElement = document.activeElement;
                uiService.activateElement(el);

                el.addEventListener("keydown", trapFocus);

                if (firstTabableEl) {
                    if (!el.contains(document.activeElement)) {
                        firstTabableEl.focus();
                    }
                } else if (el !== document.activeElement) {
                    el.focus();
                }
                return async () => {
                    // Components are destroyed from top to bottom, meaning that this cleanup is
                    // called before the ones of children. As a consequence, event handlers added on
                    // the current active element in children aren't removed yet, and can thus be
                    // executed if we deactivate that active element right away (e.g. the blur and
                    // change events could be triggered). For that reason, we wait for a micro-tick.
                    await Promise.resolve();
                    uiService.deactivateElement(el);
                    el.removeEventListener("keydown", trapFocus);

                    /**
                     * The active element may no longer contain the focus
                     * (e.g. ConfirmationDialog disables its confirm button
                     * on click, losing focus) — restore it to the previous
                     * active element in that case too. That element may
                     * itself have left the DOM meanwhile (dialog A closing
                     * after dialog B opened over it): focusing a detached
                     * node is a silent no-op that drops focus on <body>, so
                     * fall back to the new UI active element instead.
                     */
                    if (
                        el.contains(document.activeElement) ||
                        document.activeElement === document.body
                    ) {
                        if (oldActiveElement.isConnected) {
                            /** @type {HTMLElement} */ (oldActiveElement).focus();
                        } else {
                            const [firstTabableEl] = getFirstAndLastTabableElements(
                                /** @type {HTMLElement} */ (uiService.activeElement),
                            );
                            firstTabableEl?.focus();
                        }
                    }
                };
            }
        },
        () => [ref.el],
    );
}

// window size handling
export const MEDIAS_BREAKPOINTS = [
    { maxWidth: 575 },
    { minWidth: 576, maxWidth: 767 },
    { minWidth: 768, maxWidth: 991 },
    { minWidth: 992, maxWidth: 1199 },
    { minWidth: 1200, maxWidth: 1399 },
    { minWidth: 1400 },
];

/**
 * Create the MediaQueryList used both by the uiService and config from
 * `MEDIA_BREAKPOINTS`.
 *
 * @returns {MediaQueryList[]}
 */
export function getMediaQueryLists() {
    return MEDIAS_BREAKPOINTS.map(({ minWidth, maxWidth }) => {
        if (!maxWidth) {
            return window.matchMedia(`(min-width: ${minWidth}px)`);
        }
        if (!minWidth) {
            return window.matchMedia(`(max-width: ${maxWidth}px)`);
        }
        return window.matchMedia(
            `(min-width: ${minWidth}px) and (max-width: ${maxWidth}px)`,
        );
    });
}

// window size handling.
let MEDIAS = getMediaQueryLists();
let updateSizeHandler = null;

export const utils = {
    getSize() {
        return MEDIAS.findIndex((media) => media.matches);
    },
    isSmall(/** @type {{ size?: number }} */ ui = {}) {
        return (ui.size ?? utils.getSize()) <= SIZES.SM;
    },
};

const bus = new EventBus();

/**
 * Core UI service providing block/unblock, active element management,
 * and responsive size tracking.
 */
export const uiService = {
    /** @param {import("@web/env").OdooEnv} env */
    start(env) {
        // block/unblock code
        registry
            .category("main_components")
            .add(
                "BlockUI",
                /** @type {any} */ ({ Component: BlockUI, props: { bus } }),
            );

        let blockCount = 0;
        /** @param {{ message?: string, delay?: number }} [data] */
        function block(data) {
            blockCount++;
            ui.blocked = true;
            // TODO could probably be improved to handle multiple block demands
            // but that have different messages and delays
            if (blockCount === 1) {
                bus.trigger(AppEvent.BLOCK, {
                    message: data?.message,
                    delay: data?.delay,
                });
            }
        }
        function unblock() {
            blockCount--;
            if (blockCount < 0) {
                console.warn(
                    "Unblock ui was called more times than block, you should only unblock the UI if you have previously blocked it.",
                );
                blockCount = 0;
            }
            if (blockCount === 0) {
                ui.blocked = false;
                bus.trigger(AppEvent.UNBLOCK);
            }
        }

        // UI active element code
        /** @type {(Document | HTMLElement)[]} */
        let activeElems = [document];

        function activateElement(/** @type {HTMLElement} */ el) {
            activeElems.push(el);
            ui.activeElement = el;
            bus.trigger(AppEvent.ACTIVE_ELEMENT_CHANGED, el);
        }
        function deactivateElement(/** @type {HTMLElement} */ el) {
            activeElems = activeElems.filter((x) => x !== el);
            ui.activeElement = activeElems.at(-1);
            bus.trigger(AppEvent.ACTIVE_ELEMENT_CHANGED, ui.activeElement);
        }
        function getActiveElementOf(/** @type {Node} */ el) {
            for (const activeElement of activeElems.toReversed()) {
                if (activeElement.contains(el)) {
                    return activeElement;
                }
            }
        }

        if (updateSizeHandler) {
            MEDIAS.forEach((m) => m.removeEventListener?.("change", updateSizeHandler));
            MEDIAS = getMediaQueryLists();
        }

        const ui = reactive({
            bus,
            size: utils.getSize(),
            // Plain reactive properties (assigned in activate/deactivate and
            // block/unblock): getters over closure state would be invisible
            // to OWL reactivity, so `useState(useService("ui"))` consumers
            // would silently never re-render on them.
            activeElement: /** @type {Document | HTMLElement} */ (document),
            blocked: false,
            get isBlocked() {
                return blockCount > 0;
            },
            isSmall: utils.isSmall(),
            block,
            unblock,
            activateElement,
            deactivateElement,
            getActiveElementOf,
        });

        // listen to media query status changes
        updateSizeHandler = (ev) => {
            if (ev.matches) {
                ui.size = MEDIAS.indexOf(ev.target);
                ui.isSmall = utils.isSmall(ui);
                bus.trigger(AppEvent.RESIZE);
            }
        };
        MEDIAS.forEach((m) => m.addEventListener?.("change", updateSizeHandler));

        Object.defineProperty(env, "isSmall", {
            get() {
                return ui.isSmall;
            },
        });

        return ui;
    },
};

registry.category("services").add("ui", uiService);
