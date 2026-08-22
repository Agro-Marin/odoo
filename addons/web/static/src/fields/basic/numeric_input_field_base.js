// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { InvalidNumberError } from "@web/core/parsers";
import { FieldComponent } from "@web/fields/field_component";
import { useInputField } from "@web/fields/input_field_hook";
import { useNumpadDecimal } from "@web/fields/numpad_decimal_hook";

export class NumericInputFieldBase extends FieldComponent {
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
        return this.field.value;
    }

    /**
     * @returns {string}
     */
    get rawValue() {
        return this.value === false ? "" : String(this.value);
    }

    /**
     * @abstract
     * @param {boolean} humanReadable
     * @returns {string}
     */
    formatValue(humanReadable) {
        throw new Error(
            `${this.constructor.name} must implement formatValue(humanReadable)`,
        );
    }

    /** @returns {string} */
    get formattedValue() {
        if (
            !this.props.formatNumber ||
            (this.props.inputType === "number" && !this.props.readonly)
        ) {
            return this.rawValue;
        }
        return this.formatValue(
            Boolean(this.props.humanReadable) && !this.state.hasFocus,
        );
    }
}
