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
                return () => {
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
                        if (oldActiveElement?.isConnected) {
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

export const MEDIAS_BREAKPOINTS = [
    { maxWidth: 575 },
    { minWidth: 576, maxWidth: 767 },
    { minWidth: 768, maxWidth: 991 },
    { minWidth: 992, maxWidth: 1199 },
    { minWidth: 1200, maxWidth: 1399 },
    { minWidth: 1400 },
];

/**
 * Build the `MediaQueryList`s matching `MEDIAS_BREAKPOINTS`.
 *
 * @returns {MediaQueryList[]}
 */
function getMediaQueryLists() {
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

/**
 * Breakpoint list backing the service-free `utils.getSize()` used by the ~20
 * call sites (`Dropdown.isBottomSheet`, view components, …) that need the
 * current size without holding an env. Built on first use and never listened
 * to: each `uiService.start` owns its own list and its own listeners.
 * @type {MediaQueryList[] | null}
 */
let sharedMedias = null;

export const utils = {
    getSize() {
        sharedMedias ??= getMediaQueryLists();
        return sharedMedias.findIndex((media) => media.matches);
    },
    isSmall(/** @type {{ size?: number }} */ ui = {}) {
        return (ui.size ?? utils.getSize()) <= SIZES.SM;
    },
};

/**
 * Core UI service providing block/unblock, active element management,
 * and responsive size tracking.
 */
export const uiService = {
    /** @param {import("@web/env").OdooEnv} env */
    start(env) {
        /**
         * Per-start, not module-global: two envs (webclient plus an embedded
         * or test one) each get their own channel, so blocking in one no
         * longer shows the spinner in the other.
         */
        const bus = new EventBus();
        const medias = getMediaQueryLists();

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
            ui.isBlocked = true;
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
                // Nothing was blocked, so nothing was unblocked: announcing it
                // would make listeners undo state they never set.
                return;
            }
            if (blockCount === 0) {
                ui.isBlocked = false;
                bus.trigger(AppEvent.UNBLOCK);
            }
        }

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

        const getSize = () => medias.findIndex((media) => media.matches);

        /** @param {MediaQueryListEvent} ev */
        const updateSize = (ev) => {
            if (ev.matches) {
                ui.size = medias.indexOf(/** @type {any} */ (ev.target));
                ui.isSmall = ui.size <= SIZES.SM;
                bus.trigger(AppEvent.RESIZE);
            }
        };

        const ui = reactive({
            bus,
            size: getSize(),
            activeElement: /** @type {Document | HTMLElement} */ (document),
            isBlocked: false,
            isSmall: getSize() <= SIZES.SM,
            block,
            unblock,
            activateElement,
            deactivateElement,
            getActiveElementOf,
            /**
             * Service-teardown hook (see `makeEnv().destroy`). Without it the
             * breakpoint listeners outlive their env and keep writing `size` /
             * `isSmall` into a `ui` nobody reads any more on every resize.
             */
            destroy() {
                for (const media of medias) {
                    media.removeEventListener?.("change", updateSize);
                }
            },
        });

        for (const media of medias) {
            media.addEventListener?.("change", updateSize);
        }

        Object.defineProperty(env, "isSmall", {
            configurable: true,
            get() {
                return ui.isSmall;
            },
        });

        return ui;
    },
};

registry.category("services").add("ui", uiService);
