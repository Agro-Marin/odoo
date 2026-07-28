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

        useHotkey(
            "Enter",
            ({ area }) => {
                if (this.props.disabled) {
                    return;
                }
                const input = /** @type {HTMLInputElement} */ (
                    area.querySelector("input")
                );
                this.toggle(input, !(this.props.value ?? input.checked));
            },
            {
                area: () => /** @type {HTMLElement} */ (this.rootRef.el),
                bypassEditableProtection: true,
            },
        );
    }

    /**
     * Applies `checked` to the DOM, notifies the parent, and — when the parent
     * owns the value — re-asserts `props.value` onto the input.
     *
     * The re-render is what keeps a controlled checkbox honest: a click writes
     * `input.checked` out of band, and owl only rewrites that property while
     * patching this component. A parent that rejects the change (validation,
     * failed save, access rule) changes no prop, so owl skips re-rendering the
     * child entirely and the box keeps showing a value the model never took.
     *
     * @param {HTMLInputElement} input
     * @param {boolean} checked
     */
    toggle(input, checked) {
        input.checked = checked;
        this.props.onChange(checked);
        if (this.props.value !== undefined) {
            this.render();
        }
    }

    onClick(ev) {
        if (ev.composedPath().find((el) => ["INPUT", "LABEL"].includes(el.tagName))) {
            ev.stopPropagation();
            return;
        }

        const input = /** @type {HTMLInputElement} */ (
            /** @type {HTMLElement} */ (this.rootRef.el).querySelector("input")
        );
        input.focus();
        if (!this.props.disabled) {
            ev.stopPropagation();
            this.toggle(input, !input.checked);
        }
    }

    onChange(ev) {
        if (this.props.disabled) {
            return;
        }
        this.toggle(/** @type {HTMLInputElement} */ (ev.target), ev.target.checked);
    }
}
