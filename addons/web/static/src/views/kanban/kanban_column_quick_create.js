// @ts-check
/** @odoo-module native */

import { Component, onPatched, useExternalListener, useRef, useState } from "@odoo/owl";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useAutofocus, useService } from "@web/core/utils/hooks";

export class KanbanColumnQuickCreate extends Component {
    static template = "web.KanbanColumnQuickCreate";
    static props = {
        onFoldChange: Function,
        onValidate: Function,
        folded: Boolean,
        groupByField: Object,
    };

    /** @type {import("@odoo/owl").Ref} */
    inputRef;
    /** @type {import("@odoo/owl").Ref} */
    root;
    /** @type {{ hasInputFocused: boolean }} */
    state;

    setup() {
        this.dialog = useService("dialog");
        this.root = useRef("root");
        this.state = useState({
            hasInputFocused: false,
        });

        useAutofocus();
        this.inputRef = useRef("autofocus");

        useExternalListener(window, "mousedown", (/** @type {Event} */ ev) => {
            this.mousedownTarget = ev.target;
        });
        useExternalListener(
            window,
            "click",
            (/** @type {Event} */ ev) => {
                const target = /** @type {Node} */ (this.mousedownTarget || ev.target);
                const gotClickedInside = /** @type {HTMLElement} */ (
                    this.root.el
                ).contains(target);
                if (!gotClickedInside) {
                    this.fold();
                }
                this.mousedownTarget = null;
            },
            { capture: true },
        );

        useHotkey("escape", () => this.fold());
        onPatched(() => {
            if (this.state.hasInputFocused && !this.props.folded) {
                this.root.el?.scrollIntoView({ behavior: "smooth" });
            }
        });
    }

    /** @returns {string} */
    get relatedFieldName() {
        return this.props.groupByField.string;
    }

    fold() {
        this.props.onFoldChange(true);
    }

    unfold() {
        this.props.onFoldChange(false);
    }

    validate() {
        const inputEl = /** @type {HTMLInputElement} */ (this.inputRef.el);
        const title = inputEl.value.trim();
        if (title.length) {
            this.props.onValidate(title);
            inputEl.value = "";
            inputEl.focus();
            this.state.hasInputFocused = true;
        }
    }

    /**
     * @param {KeyboardEvent} ev
     */
    onInputKeydown(ev) {
        if (ev.key === "Enter") {
            this.validate();
        }
    }
}
