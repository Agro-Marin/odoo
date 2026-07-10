// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/percentage/percentage_field - Numeric input field that displays and parses percentage values */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { extractDigits } from "@web/fields/field_utils";
import { formatPercentage } from "@web/fields/formatters";
import { parsePercentage } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class PercentageField extends NumericInputFieldBase {
    static template = "web.PercentageField";
    static props = {
        ...standardFieldProps,
        digits: { type: Array, optional: true },
    };

    /** @param {string} v @returns {number} */
    parse(v) {
        return parsePercentage(v);
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
    extractProps: ({ attrs, options }) => ({
        digits: extractDigits({ attrs, options }),
    }),
};

registerField("percentage", percentageField);
