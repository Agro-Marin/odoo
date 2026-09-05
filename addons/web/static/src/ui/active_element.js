// @ts-check
/** @odoo-module native */

import { useEffect, useRef } from "@odoo/owl";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { useOwnedActiveElement } from "@web/core/utils/active_element_scope";
import { getTabableElements, isFocusable } from "@web/core/utils/dom/ui";
import { useService } from "@web/core/utils/hooks";

/**
 * @param {HTMLElement} el
 * @returns {[HTMLElement | undefined, HTMLElement | undefined]}
 */
export function getFirstAndLastTabableElements(el) {
    const tabableEls = getTabableElements(el);
    return [tabableEls[0], tabableEls.at(-1)];
}

/**
 * @param {KeyboardEvent} e
 */
function trapFocus(e) {
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
                firstTabableEl?.focus();
                e.preventDefault();
                e.stopPropagation();
            }
            break;
        case "shift+tab":
            if (document.activeElement === firstTabableEl) {
                lastTabableEl?.focus();
                e.preventDefault();
                e.stopPropagation();
            }
            break;
    }
}

/**
 * Claims the UI for the referenced element: it becomes the scope hotkeys and
 * commands are dispatched to, and it traps the focus.
 *
 * @param {string} refName
 */
export function useActiveElement(refName) {
    if (!refName) {
        throw new Error("refName not given to useActiveElement");
    }
    const uiService = useService("ui");
    const ref = useRef(refName);
    const scope = useOwnedActiveElement();

    useEffect(
        (el) => {
            if (el) {
                const [firstTabableEl] = getFirstAndLastTabableElements(el);
                // Claiming the scope and moving the focus are two decisions.
                // An element with nothing to focus still owns its hotkeys and
                // commands; it just must not steal the focus to say so.
                const takesFocus = Boolean(firstTabableEl) || isFocusable(el);
                const oldActiveElement = document.activeElement;
                scope.el = el;
                uiService.activateElement(el);

                el.addEventListener("keydown", trapFocus);

                if (firstTabableEl) {
                    if (!el.contains(document.activeElement)) {
                        firstTabableEl.focus();
                    }
                } else if (isFocusable(el) && el !== document.activeElement) {
                    el.focus();
                }
                return () => {
                    scope.el = null;
                    uiService.deactivateElement(el);
                    el.removeEventListener("keydown", trapFocus);

                    if (
                        takesFocus &&
                        (el.contains(document.activeElement) ||
                            document.activeElement === document.body)
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
