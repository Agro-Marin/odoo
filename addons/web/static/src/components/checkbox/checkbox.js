// @ts-check
/** @odoo-module native */

/** @module @web/components/checkbox/checkbox */

import { Component, onPatched, status, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
/**
 * @extends Component
 */

export class CheckBox extends Component {
    static template = "web.CheckBox";
    static nextId = 1;
    static warnedRevert = new Set();
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

        onPatched(() => this.syncWithValue());

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

    /** @returns {HTMLInputElement | null} */
    get input() {
        return this.rootRef.el?.querySelector("input") ?? null;
    }

    /**
     * @returns {boolean}
     */
    syncWithValue() {
        const input = this.input;
        if (
            input &&
            this.props.value !== undefined &&
            input.checked !== this.props.value
        ) {
            input.checked = this.props.value;
            return true;
        }
        return false;
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
                if (!CheckBox.warnedRevert.has(this.constructor)) {
                    CheckBox.warnedRevert.add(this.constructor);
                    console.warn(
                        "[CheckBox] reverted a click because `value` never moved. " +
                            "Either the parent rejected the change, or it stored it " +
                            "somewhere owl cannot see (a plain Set/Map/field instead " +
                            "of `useState`) — in which case the model took the change " +
                            "and only the box snapped back.",
                    );
                }
            });
    }

    /** @param {MouseEvent} ev */
    onClick(ev) {
        if (
            ev
                .composedPath()
                .find((el) =>
                    ["INPUT", "LABEL"].includes(/** @type {Element} */ (el).tagName),
                )
        ) {
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

    /** @param {Event} ev */
    onChange(ev) {
        if (this.props.disabled) {
            return;
        }
        const input = /** @type {HTMLInputElement} */ (ev.target);
        this.toggle(input, input.checked);
    }
}
