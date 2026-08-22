// @ts-check
/** @odoo-module native */

import { Component, status, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { useSyncedInputProperty } from "@web/core/utils/hooks";

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

        this.syncWithValue = useSyncedInputProperty(
            () => this.input,
            () => this.props.value,
            { property: "checked" },
        );

        useHotkey(
            "Enter",
            () => {
                if (this.props.disabled) {
                    return;
                }
                const input = this.input;
                if (!input) {
                    return;
                }
                this.toggle(input, !(this.props.value ?? input.checked));
            },
            {
                area: () => /** @type {HTMLElement} */ (this.rootRef.el),
                bypassEditableProtection: true,
            },
        );
    }

    /** @returns {HTMLInputElement | null} */
    get input() {
        return this.rootRef.el?.querySelector("input") ?? null;
    }
    /**
     * @param {HTMLInputElement} input
     * @param {boolean} checked
     */
    toggle(input, checked) {
        input.checked = checked;
        const changed = this.props.onChange(checked);
        if (this.props.value === undefined) {
            return;
        }
        Promise.resolve(changed)
            .then(
                () => new Promise((resolve) => browser.requestAnimationFrame(resolve)),
            )
            .then(() => {
                if (status(this) === "destroyed" || !this.syncWithValue()) {
                    return;
                }
                if (!this.env.debug) {
                    return;
                }
                console.warn(
                    "[CheckBox] reverted a click because `value` never moved. " +
                        "Either the parent rejected the change, or it stored it " +
                        "somewhere owl cannot see (a plain Set/Map/field instead " +
                        "of `useState`) — in which case the model took the change " +
                        "and only the box snapped back.",
                );
            });
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        if (
            ev
                .composedPath()
                .some((el) =>
                    ["INPUT", "LABEL"].includes(/** @type {Element} */ (el).tagName),
                )
        ) {
            ev.stopPropagation();
            return;
        }

        const input = this.input;
        if (!input) {
            return;
        }
        input.focus();
        if (!this.props.disabled) {
            ev.stopPropagation();
            this.toggle(input, !input.checked);
        }
    }

    /** @param {Event} ev */
    onChange(ev) {
        if (this.props.disabled) {
            return;
        }
        const input = /** @type {HTMLInputElement} */ (ev.target);
        this.toggle(input, input.checked);
    }
}
