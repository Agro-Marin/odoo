// @ts-check
/** @odoo-module native */

import { formatFieldFloat } from "@web/core/formatters";
import { parseFloat } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { registerField } from "@web/fields/_registry";
import {
    digitsAttribute,
    enableFormattingOption,
    hideTrailingZerosOption,
    humanReadableOptions,
    numericInputOptions,
} from "@web/fields/field_options";
import { extractNumericOptions, isFalseEmpty } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class FloatField extends NumericInputFieldBase {
    static template = "web.FloatField";
    static props = {
        ...standardFieldProps,
        formatNumber: { type: Boolean, optional: true },
        inputType: { type: String, optional: true },
        step: { type: Number, optional: true },
        digits: { type: Array, optional: true },
        minDigits: { type: Number, optional: true },
        humanReadable: { type: Boolean, optional: true },
        decimals: { type: Number, optional: true },
        trailingZeros: { type: Boolean, optional: true },
    };
    static defaultProps = {
        formatNumber: true,
        inputType: "text",
        humanReadable: false,
        decimals: 0,
        trailingZeros: true,
    };

    /**
     * @param {string} value
     * @returns {number | import("@web/core/utils/operation").Operation}
     */
    parse(value) {
        return this.parseNumericInput(value, (v) =>
            parseFloat(v, { allowOperation: true }),
        );
    }

    /**
     * @param {boolean} humanReadable
     * @returns {string}
     */
    formatValue(humanReadable) {
        return formatFieldFloat(this.value, {
            digits: this.props.digits,
            minDigits: this.props.minDigits,
            field: this.field.definition,
            trailingZeros: this.props.trailingZeros,
            humanReadable,
            ...(humanReadable ? { decimals: this.props.decimals } : {}),
        });
    }
}

export const floatField = {
    component: FloatField,
    displayName: _t("Float"),
    supportedOptions: [
        enableFormattingOption(),
        {
            label: _t("Digits"),
            name: "digits",
            type: "digits",
        },
        {
            label: _t("Minimum Digits"),
            name: "min_display_digits",
            type: "digits",
        },
        ...numericInputOptions(),
        ...humanReadableOptions(),
        hideTrailingZerosOption(),
    ],
    supportedAttributes: [digitsAttribute()],
    supportedTypes: ["float", "monetary"],
    isEmpty: isFalseEmpty,
    /**
     * @param {{ attrs: any, options: any }} param0
     * @param {any} _dynamicInfo
     */
    extractProps: ({ attrs, options }, _dynamicInfo) => ({
        ...extractNumericOptions({ options }),
        digits: extractDigits({ attrs, options }),
        minDigits: options.min_display_digits,
        trailingZeros: !options.hide_trailing_zeros,
    }),
};

registerField("float", floatField);
