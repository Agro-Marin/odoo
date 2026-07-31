// @ts-check
/** @odoo-module native */

/** @module @web/ui/ui_service */

import { EventBus, reactive, useEffect, useRef } from "@odoo/owl";
import { mainComponentEntry } from "@web/components/main_components_container";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { getTabableElements, isFocusable } from "@web/core/utils/dom/ui";
import { useService } from "@web/core/utils/hooks";
import { BlockUI } from "@web/ui/block/block_ui";
import { getMediaQueryLists, sizeOf, SIZES } from "@web/ui/viewport";

/**
 * @param {HTMLElement} el
 * @returns {[HTMLElement | undefined, HTMLElement | undefined]}
 */
export function getFirstAndLastTabableElements(el) {
    const tabableEls = getTabableElements(el);
    return [tabableEls[0], tabableEls.at(-1)];
}

/**
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

export const uiService = {
    /** @param {import("@web/env").OdooEnv} env */
    start(env) {
        const bus = new EventBus();
        const medias = getMediaQueryLists();

        registry
            .category("main_components")
            .add("BlockUI", mainComponentEntry(BlockUI));

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
            for (let i = activeElems.length - 1; i >= 0; i--) {
                if (activeElems[i].contains(el)) {
                    return activeElems[i];
                }
            }
        }

        const getSize = () => sizeOf(medias);

        const updateSize = () => {
            const size = getSize();
            if (size === ui.size) {
                return;
            }
            ui.size = size;
            ui.isSmall = size <= SIZES.SM;
            bus.trigger(AppEvent.RESIZE);
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
