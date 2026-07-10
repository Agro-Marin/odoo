// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_selection_hook - Alt-key tracker that toggles ``state.selectionAvailable`` for kanban's range-select affordance */

import { useEffect } from "@odoo/owl";

/**
 * Wire ``state.selectionAvailable`` to the live Alt-key state: the kanban
 * template hides each card's bulk-select checkbox until Alt is held, so the
 * flag drives that affordance.
 *
 * Listens on ``window`` (not ``rootRef``) since Alt may be pressed outside
 * the kanban surface. ``keyup`` clears the flag on release of *any* key, not
 * just Alt (missing that would leave it stuck if another key is released
 * first); ``blur`` mirrors it so alt-tabbing away doesn't strand the UI in
 * selection mode. All three listeners are torn down with the component.
 *
 * @param {{ selectionAvailable: boolean }} state Reactive bag mutated on
 *   Alt-key transitions; owned by the caller (kept alongside ``processedIds``
 *   in its ``useState`` cluster).
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
