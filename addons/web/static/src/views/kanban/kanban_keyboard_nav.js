// @ts-check
/** @odoo-module native */

import { SearchModelEvent } from "@web/core/events";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";

/**
 * @typedef {object} KanbanKeyboardNavOptions
 * @property {{ el: HTMLElement | null }} rootRef
 * @property {() => boolean} getCanOpenRecords
 * @property {() => boolean} getQuickCreateActive
 * @property {(target: HTMLElement, isRange?: boolean) => void} onSpace
 * @property {(area: HTMLElement, direction: "up" | "down" | "left" | "right") => boolean} onArrowNav
 * @property {any} [searchModel]
 */

/**
 * @param {KanbanKeyboardNavOptions} options
 */
export function useKanbanKeyboardNavigation(options) {
    const {
        rootRef,
        getCanOpenRecords,
        getQuickCreateActive,
        onSpace,
        onArrowNav,
        searchModel,
    } = options;
    const area = () => rootRef.el;

    useHotkey(
        "Enter",
        ({ target: _target }) => {
            const target = /** @type {HTMLElement} */ (_target);
            if (target.closest(".o_kanban_selection_active") !== null) {
                return;
            }
            if (!target.classList.contains("o_kanban_record")) {
                return;
            }
            if (getCanOpenRecords()) {
                target.click();
                return;
            }
            const firstLink = target.querySelector("a, button");
            if (firstLink) {
                /** @type {HTMLElement} */ (firstLink).click();
            }
        },
        { area },
    );

    useHotkey("space", ({ target }) => onSpace(/** @type {HTMLElement} */ (target)), {
        area,
        isAvailable: () => !getQuickCreateActive(),
    });

    useHotkey(
        "shift+space",
        ({ target }) => onSpace(/** @type {HTMLElement} */ (target), true),
        {
            area,
            isAvailable: () => !getQuickCreateActive(),
        },
    );

    const arrowsOptions = { area, allowRepeat: true };
    useHotkey(
        "ArrowUp",
        ({ area: el }) => {
            if (!onArrowNav(el, "up")) {
                searchModel?.trigger(SearchModelEvent.FOCUS_SEARCH);
            }
        },
        arrowsOptions,
    );
    useHotkey("ArrowDown", ({ area: el }) => onArrowNav(el, "down"), arrowsOptions);
    useHotkey("ArrowLeft", ({ area: el }) => onArrowNav(el, "left"), arrowsOptions);
    useHotkey("ArrowRight", ({ area: el }) => onArrowNav(el, "right"), arrowsOptions);
}
