// @ts-check
/** @odoo-module native */

import { Component, useExternalListener, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { hasTouch, isMacOS } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class FooterComponent extends Component {
    static template = "web.HomeMenu.CommandPalette.Footer";
    static props = {
        switchNamespace: { type: Function, optional: true },
    };

    setup() {
        this.controlKey = isMacOS() ? "COMMAND" : "CONTROL";
    }
}

/**
 * @param {{ onQueryChanged: () => void }} params called when the query moves,
 *  since what it invalidates -- a keyboard selection into the grid -- belongs
 *  to the component and not here
 */
export function useHomeMenuSearch({ onQueryChanged }) {
    const command = useService("command");
    const ui = useService("ui");
    const inputRef = useRef("input");
    const state = useState({ query: "" });
    /** Mid-composition (an IME): the box holds a half-typed character. */
    let composing = false;

    /** @returns {HTMLInputElement | null} */
    const inputEl = () => /** @type {HTMLInputElement | null} */ (inputRef.el);

    const search = {
        get query() {
            return state.query;
        },

        get inputEl() {
            return inputEl();
        },

        focus() {
            const el = inputEl();
            if (el && !ui.isSmall) {
                el.focus({ preventScroll: true });
            }
        },

        clear() {
            state.query = "";
            const el = inputEl();
            if (el) {
                el.value = "";
            }
            onQueryChanged();
        },

        onInput() {
            const typed = composing ? "" : (inputEl()?.value.trim() ?? "");
            composing = false;
            const namespaced =
                typed.length > 0 &&
                registry.category("command_setup").contains(typed[0]);
            if (!namespaced) {
                state.query = typed;
                onQueryChanged();
                return;
            }
            search.clear();
            command.openMainPalette(
                /** @type {any} */ ({ searchValue: typed, FooterComponent }),
                () => search.focus(),
            );
        },

        onBlur() {
            if (hasTouch()) {
                return;
            }
            browser.setTimeout(() => {
                if (
                    document.activeElement === document.body &&
                    ui.activeElement === document
                ) {
                    search.focus();
                }
            });
        },

        onCompositionStart() {
            composing = true;
        },
    };

    useExternalListener(window, "keydown", (/** @type {KeyboardEvent} */ ev) => {
        const printable =
            ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey;
        if (
            printable &&
            document.activeElement !== inputRef.el &&
            ui.activeElement === document &&
            !["TEXTAREA", "INPUT"].includes(document.activeElement?.tagName ?? "")
        ) {
            search.focus();
        }
    });

    return search;
}
