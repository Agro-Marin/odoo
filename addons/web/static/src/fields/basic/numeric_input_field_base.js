// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/numeric_input_field_base */

import { Component, useState } from "@odoo/owl";
import { InvalidNumberError } from "@web/core/parsers";
import { useInputField } from "@web/fields/input_field_hook";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";

export class NumericInputFieldBase extends Component {
    /** @type {{ hasFocus: boolean }} */
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
     * @param {string} value
     * @param {(v: string) => number} localeParse
     * @param {{ integer?: boolean }} [options]
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
                    throw new InvalidNumberError(`"${value}" is not a correct integer`);
                }
                return parsed;
            }
        }
        return localeParse(value);
    }

    /** @returns {number | false} */
    get value() {
        return this.props.record.data[this.props.name];
    }

    /**
     * @returns {string}
     */
    get rawValue() {
        return this.value === false ? "" : String(this.value);
    }
}
