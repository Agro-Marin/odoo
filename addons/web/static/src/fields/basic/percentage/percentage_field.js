// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/percentage/percentage_field - Numeric input field that displays and parses percentage values */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { extractDigits, isFalseEmpty } from "@web/fields/field_utils";
import { formatPercentage } from "@web/fields/formatters";
import { parsePercentage } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { Operation } from "@web/model/relational_model/operation";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class PercentageField extends NumericInputFieldBase {
    static template = "web.PercentageField";
    static props = {
        ...standardFieldProps,
        digits: { type: Array, optional: true },
    };

    /** @param {string} v @returns {number | Operation} */
    parse(v) {
        const parsed = parsePercentage(v, { allowOperation: true });
        if (parsed instanceof Operation) {
            // The operation is entered in DISPLAYED units (value × 100), so an
            // additive operand ("+= 5" meaning +5 percentage points) must be
            // scaled back to storage units (0.05). Multiplicative operations
            // (*= / /=) are scale-invariant. Mirrors FloatFactorField.parse.
            if (parsed.operator === "+" || parsed.operator === "-") {
                return new Operation(parsed.operator, parsed.operand / 100);
            }
            return parsed;
        }
        return parsed;
    }

    /**
     * @returns {string} value formatted without the % symbol — this is what
     *     is written into the input; the template renders the symbol in a
     *     separate <span>.
     */
    get formattedValue() {
        return formatPercentage(this.value, {
            digits: this.props.digits,
            noSymbol: true,
            field: this.props.record.fields[this.props.name],
        });
    }

    /** @returns {string} value formatted with the % symbol, for readonly display */
    get formattedValueWithSymbol() {
        return formatPercentage(this.value, {
            digits: this.props.digits,
            field: this.props.record.fields[this.props.name],
        });
    }
}

export const percentageField = {
    component: PercentageField,
    displayName: _t("Percentage"),
    supportedTypes: ["integer", "float"],
    isEmpty: isFalseEmpty,
    extractProps: ({ attrs, options }) => ({
        digits: extractDigits({ attrs, options }),
    }),
};

registerField("percentage", percentageField);
