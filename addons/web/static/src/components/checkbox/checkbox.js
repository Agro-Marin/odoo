// @ts-check
/** @odoo-module native */

/** @module @web/components/checkbox/checkbox - Accessible checkbox component with label slot and hotkey support */

import { Component, onPatched, status, useRef } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
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
    /** Components already warned about a reverted click (see toggle). */
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

        // A click writes `input.checked` out of band, so the DOM can drift from
        // `value` without owl noticing. Re-assert it after every patch: an
        // accepted change lands whether the parent moved its state
        // synchronously or only after an await.
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
     * Force the input back onto `props.value`, the single source of truth for
     * a controlled checkbox.
     *
     * @returns {boolean} whether the DOM had drifted and was corrected
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
     * Applies `checked` to the DOM and notifies the parent.
     *
     * When `value` is given the checkbox is CONTROLLED: that prop, not the
     * DOM, is the truth, so the out-of-band write above has to be reconciled
     * against it. The reconciliation is deferred by a frame on purpose — at
     * this instant `props.value` is still, by definition, the pre-click value,
     * so reconciling now would undo every change the parent accepts and leave
     * a later patch to put it back (a visible bounce). Deferring lets an
     * accepted change — sync state, or an awaited `record.update` that
     * resolves within the frame — settle first, and only a parent that moved
     * nothing gets reverted.
     *
     * This used to call `this.render()` instead, which re-ran the template and
     * the default slot on every single click to achieve the same thing.
     *
     * @param {HTMLInputElement} input
     * @param {boolean} checked
     */
    toggle(input, checked) {
        input.checked = checked;
        this.props.onChange(checked);
        if (this.props.value === undefined) {
            // Uncontrolled: the DOM owns the value, there is nothing to
            // reconcile it against.
            return;
        }
        browser.requestAnimationFrame(() => {
            if (status(this) === "destroyed" || !this.syncWithValue()) {
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
