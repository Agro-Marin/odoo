// @ts-check
/** @odoo-module native */

/** @module @web/ui/ui_service - UI service: active element stack, block/unblock, and viewport size tracking */

import { EventBus, reactive, useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { getTabableElements, isFocusable } from "@web/core/utils/dom/ui";
import { useService } from "@web/core/utils/hooks";
import { BlockUI } from "@web/ui/block/block_ui";
import { getMediaQueryLists, SIZES } from "@web/ui/viewport";

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

/** @type {any} */
const BLOCK_UI_ENTRY = { Component: BlockUI };

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

        /**
         * The SAME entry object every time, and no `force`: `main_components`
         * is one global registry shared by every env, so this add has to be
         * idempotent. A bus passed as a prop here pinned every
         * `MainComponentsContainer` on the page — whatever env it belongs to —
         * to the bus of whichever env started first; `BlockUI` resolves the bus
         * from its own env instead. Re-registering a fresh object would also
         * make a second env's start either warn (without `force`) or wipe an
         * addon's override of this key (with it).
         */
        registry.category("main_components").add("BlockUI", BLOCK_UI_ENTRY);

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
            // Walked backwards in place: this runs on hotkey dispatch and on
            // every popover click-away test, and `toReversed()` copied the
            // whole stack each time to read at most a couple of entries.
            for (let i = activeElems.length - 1; i >= 0; i--) {
                if (activeElems[i].contains(el)) {
                    return activeElems[i];
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

        const initialSize = getSize();
        const ui = reactive({
            bus,
            size: initialSize,
            activeElement: /** @type {Document | HTMLElement} */ (document),
            isBlocked: false,
            isSmall: initialSize <= SIZES.SM,
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
