// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/numeric_input_field_base - Abstract base class for numeric input fields with shared focus and parse logic */

import { Component, useState } from "@odoo/owl";
import { useInputField } from "@web/fields/input_field_hook";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";

/**
 * Base class for numeric input fields (integer, float, etc.).
 *
 * Provides shared infrastructure: hasFocus state, useInputField wiring
 * (getValue → formattedValue, parse via this.parse()), useNumpadDecimal,
 * focus event handlers, and the raw value getter.
 *
 * Subclasses must implement:
 *   - parse(value)       — parses the raw input string into a typed value
 *   - get formattedValue — returns the display value (format varies per type)
 */
export class NumericInputFieldBase extends Component {
    /**
     * ``value`` is only used by MonetaryField (input-text mirror); it is
     * declared here so the subclass doesn't shadow the field (TS2612).
     * @type {{ hasFocus: boolean, value?: string }}
     */
    state;

    setup() {
        this.state = useState({ hasFocus: false });
        this.inputRef = useInputField({
            getValue: () => /** @type {any} */ (this).formattedValue,
            refName: "numpadDecimal",
            parse: (v) => /** @type {any} */ (this).parse(v),
        });
        useNumpadDecimal();
    }

    onFocusIn() {
        this.state.hasFocus = true;
    }

    onFocusOut() {
        this.state.hasFocus = false;
    }

    /**
     * Parses the raw input string, guarding the ``<input type="number">`` case
     * shared by the integer/float/monetary subclasses.
     *
     * A type=number value is always dot-decimal regardless of locale, so
     * passing it to a locale parser would misread the dot as a thousands
     * separator ("1.5" -> 15, a silent 10x error). When the input is
     * type=number and already holds a finite number, validate and return it
     * directly; otherwise (non-number input, or a non-finite value such as
     * "1e999" -> Infinity) fall back to ``localeParse``, which raises a
     * ParseError on genuinely invalid input.
     *
     * @param {string} value
     * @param {(v: string) => number} localeParse locale-aware fallback parser
     * @param {{ integer?: boolean }} [options] enforce 32-bit integer bounds
     * @returns {number}
     */
    parseNumericInput(value, localeParse, { integer = false } = {}) {
        if (this.props.inputType === "number") {
            const parsed = Number(value);
            if (Number.isFinite(parsed)) {
                if (
                    integer &&
                    (!Number.isInteger(parsed) ||
                        parsed < -2147483648 ||
                        parsed > 2147483647)
                ) {
                    throw new Error(`"${value}" is not a correct integer`);
                }
                return parsed;
            }
        }
        return localeParse(value);
    }

    /** @returns {number | false} Raw field value from the record */
    get value() {
        return this.props.record.data[this.props.name];
    }
}
