// @ts-check
/** @odoo-module native */

import { onPatched, useRef, useState } from "@odoo/owl";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";

import { nextFocusedIndex } from "./grid_navigation.js";

/** @param {{ */
export function useHomeMenuKeyboard({
    rows,
    activate,
    fallback,
    escape,
    isAvailable,
    enterTarget,
}) {
    const state = useState({ focusedIndex: /** @type {number | null} */ (null) });
    const rootRef = useRef("root");
    let followSelection = false;

    const move = (/** @type {string} */ cmd) => {
        if (rootRef.el && getComputedStyle(rootRef.el).direction === "rtl") {
            cmd =
                cmd === "nextColumn"
                    ? "previousColumn"
                    : cmd === "previousColumn"
                      ? "nextColumn"
                      : cmd;
        }
        const next = nextFocusedIndex(rows(), state.focusedIndex, cmd);
        if (next === null) {
            return;
        }
        followSelection = true;
        state.focusedIndex = next;
    };

    /** @type {[string, () => void][]} */
    const arrows = [
        ["ArrowDown", () => move("nextLine")],
        ["ArrowRight", () => move("nextColumn")],
        ["ArrowUp", () => move("previousLine")],
        ["ArrowLeft", () => move("previousColumn")],
    ];
    for (const [hotkey, callback] of arrows) {
        useHotkey(hotkey, callback, { allowRepeat: true, isAvailable });
    }
    useHotkey("Escape", () => escape());
    useHotkey(
        "Enter",
        () => (state.focusedIndex === null ? fallback() : activate(state.focusedIndex)),
        {
            allowRepeat: true,
            isAvailable: (target) => target === enterTarget(),
        },
    );

    onPatched(() => {
        if (!followSelection) {
            return;
        }
        const selected = /** @type {HTMLElement | null} */ (
            rootRef.el?.querySelector(".o_menuitem.o_focused")
        );
        if (!selected) {
            return;
        }
        followSelection = false;
        selected.focus({ preventScroll: true });
        selected.scrollIntoView({ block: "center" });
    });

    return {
        get focusedIndex() {
            return state.focusedIndex;
        },
        clear() {
            state.focusedIndex = null;
        },
        /** @param {number} index */
        focus(index) {
            state.focusedIndex = index;
        },
    };
}
