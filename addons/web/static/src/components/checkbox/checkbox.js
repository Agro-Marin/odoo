// @ts-check
/** @odoo-module native */

/** @module @web/components/checkbox/checkbox - Accessible checkbox component with label slot and hotkey support */

import { Component, useRef } from "@odoo/owl";
import { useHotkey } from "@web/services/hotkeys/hotkey_hook";
/**
 * Custom checkbox
 *
 * <CheckBox
 *    value="boolean"
 *    disabled="boolean"
 *    onChange="_onValueChange"
 * >
 *    Change the label text
 * </CheckBox>
 *
 * @extends Component
 */

export class CheckBox extends Component {
    static template = "web.CheckBox";
    static nextId = 1;
    static defaultProps = {
        onChange: () => {},
    };
    static props = {
        id: {
            type: true,
            optional: true,
        },
        disabled: {
            type: Boolean,
            optional: true,
        },
        value: {
            type: Boolean,
            optional: true,
        },
        slots: {
            type: Object,
            optional: true,
        },
        onChange: {
            type: Function,
            optional: true,
        },
        className: {
            type: String,
            optional: true,
        },
        name: {
            type: String,
            optional: true,
        },
        indeterminate: {
            type: Boolean,
            optional: true,
        },
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;

    setup() {
        this.id = `checkbox-comp-${CheckBox.nextId++}`;
        this.rootRef = useRef("root");

        // Toggle via Enter when focus is inside the root element.
        useHotkey(
            "Enter",
            ({ area }) => {
                // Match onClick/onChange: a disabled checkbox must not toggle.
                if (this.props.disabled) {
                    return;
                }
                const input = /** @type {HTMLInputElement} */ (
                    area.querySelector("input")
                );
                // Derive the next value from props (the source of truth for
                // controlled parents) and mirror it on the DOM like onClick
                // does, so the keyboard toggle is visible immediately.
                const newValue = !(this.props.value ?? input.checked);
                input.checked = newValue;
                this.props.onChange(newValue);
            },
            {
                area: () => /** @type {HTMLElement} */ (this.rootRef.el),
                bypassEditableProtection: true,
            },
        );
    }

    onClick(ev) {
        if (ev.composedPath().find((el) => ["INPUT", "LABEL"].includes(el.tagName))) {
            // The onChange will handle these cases.
            ev.stopPropagation();
            return;
        }

        // Reproduce the click event behavior as if it comes from the input element.
        const input = /** @type {HTMLInputElement} */ (
            /** @type {HTMLElement} */ (this.rootRef.el).querySelector("input")
        );
        input.focus();
        if (!this.props.disabled) {
            ev.stopPropagation();
            input.checked = !input.checked;
            this.props.onChange(input.checked);
        }
    }

    onChange(ev) {
        if (!this.props.disabled) {
            this.props.onChange(ev.target.checked);
        }
    }
}
