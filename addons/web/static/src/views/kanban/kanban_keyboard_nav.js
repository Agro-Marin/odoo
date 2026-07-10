// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_keyboard_nav - Hotkey wiring for Enter/Space/Arrow card navigation in kanban view */

import { SearchModelEvent } from "@web/core/events";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";

/**
 * @typedef {object} KanbanKeyboardNavOptions
 * @property {{ el: HTMLElement | null }} rootRef OWL ref to the kanban root.
 * @property {() => boolean} getCanOpenRecords Whether ``Enter`` on a
 *   focused card should open the record (vs. clicking the first
 *   embedded link/button). Defaults to the arch's ``canOpenRecords``.
 * @property {() => boolean} getQuickCreateActive Whether a quick-create
 *   input is currently open; hotkeys other than Enter disable while
 *   the user is typing into the quick-create form.
 * @property {(target: HTMLElement, isRange?: boolean) => void} onSpace
 *   Renderer-supplied space/shift+space handler (kept on the prototype
 *   so subclasses can override).
 * @property {(area: HTMLElement, direction: "up" | "down" | "left" | "right") => boolean}
 *   onArrowNav Renderer-supplied focus mover. Returns ``false`` when
 *   the move falls off the top edge, so the caller can hand focus
 *   back to the search bar (handled internally for ``up`` only).
 * @property {any} [searchModel] Optional searchModel reference used
 *   to bubble ``focus-search`` when ArrowUp leaves the top row.
 *   Omitted when the renderer mounts without a search context.
 */

/**
 * Install kanban keyboard navigation: ``Enter`` opens / clicks,
 * ``Space`` / ``Shift+Space`` invoke the range-select hook, arrows
 * walk the focused card.
 *
 * All hotkeys are scoped to ``rootRef.el`` via ``area`` so they don't
 * leak into ancestor components (e.g. a kanban embedded in a form
 * dialog still lets the form swallow its own keys).
 *
 * The hook does not own selection state — that lives on the renderer
 * (see {@link useKanbanSelection} for the Alt-key affordance).
 *
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
            // A card with the bulk-select checkbox active swallows Enter — the
            // checkbox should get the browser's default toggle, not open the record.
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
            // ``canOpenRecords`` is false (e.g. no detail form) — surface the first
            // interactive element in the card instead so Enter still does something.
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
    // ArrowUp card nav must always work, even without a search context
    // (x2many kanban in a form/dialog). Only the ``focus-search`` fallback
    // depends on searchModel, so guard just that.
    useHotkey(
        "ArrowUp",
        ({ area: el }) => {
            if (!onArrowNav(el, "up")) {
                // ``focus-search`` is observed by the search bar in
                // webclient/control_panel; skip when there's no search.
                searchModel?.trigger(SearchModelEvent.FOCUS_SEARCH);
            }
        },
        arrowsOptions,
    );
    useHotkey("ArrowDown", ({ area: el }) => onArrowNav(el, "down"), arrowsOptions);
    useHotkey("ArrowLeft", ({ area: el }) => onArrowNav(el, "left"), arrowsOptions);
    useHotkey("ArrowRight", ({ area: el }) => onArrowNav(el, "right"), arrowsOptions);
}
