// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_selection_hook */

import { useEffect } from "@odoo/owl";

/**
 * @param {{ selectionAvailable: boolean }} state
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
