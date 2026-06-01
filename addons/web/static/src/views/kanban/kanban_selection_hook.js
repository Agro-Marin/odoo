// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_selection_hook - Alt-key tracker that toggles ``state.selectionAvailable`` for kanban's range-select affordance */

import { useEffect } from "@odoo/owl";

/**
 * Wire ``state.selectionAvailable`` to the live Alt-key state.
 *
 * The kanban template gates the per-card checkbox affordance on this
 * reactive flag — a card's bulk-select checkbox is hidden until the
 * user holds Alt, surfacing the selection UI only when intentional.
 *
 * Three window-level listeners are installed and torn down with the
 * owning component:
 *
 *   - ``keydown`` flips the flag true when ``ev.key === "Alt"``.
 *   - ``keyup`` flips it back to false (any key release ends the mode;
 *     listening only for Alt-up would miss the case where the user
 *     releases Alt while another key is still held).
 *   - ``blur`` mirrors keyup so the flag clears when the tab loses
 *     focus mid-press (otherwise alt-tabbing leaves the UI stuck in
 *     selection mode on return).
 *
 * Window scope (rather than ``rootRef``) is intentional: the Alt key
 * may be held outside the kanban surface and we still want the flag
 * to track. Component unmount removes all three listeners.
 *
 * @param {{ selectionAvailable: boolean }} state Reactive bag whose
 *   ``selectionAvailable`` field is mutated on Alt-key transitions.
 *   The hook does not own the bag — the renderer keeps it in its
 *   ``useState`` cluster alongside ``processedIds`` and other UI flags.
 */
export function useKanbanSelection(state) {
    const onAltDown = (/** @type {KeyboardEvent} */ ev) => {
        if (ev.key === "Alt") {
            state.selectionAvailable = true;
        }
    };
    const onAltUp = () => {
        state.selectionAvailable = false;
    };
    useEffect(
        () => {
            window.addEventListener("keydown", onAltDown);
            window.addEventListener("keyup", onAltUp);
            window.addEventListener("blur", onAltUp);
            return () => {
                window.removeEventListener("keydown", onAltDown);
                window.removeEventListener("keyup", onAltUp);
                window.removeEventListener("blur", onAltUp);
            };
        },
        () => [],
    );
}
