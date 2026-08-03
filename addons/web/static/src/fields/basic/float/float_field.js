// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float/float_field */

import { formatFloat } from "@web/core/formatters";
import { parseFloat } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { registerField } from "@web/fields/_registry";
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

    /** @returns {string} */
    get formattedValue() {
        if (
            !this.props.formatNumber ||
            (this.props.inputType === "number" && !this.props.readonly)
        ) {
            return this.rawValue;
        }
        const options = {
            digits: this.props.digits,
            minDigits: this.props.minDigits,
            field: this.props.record.fields[this.props.name],
            trailingZeros: this.props.trailingZeros,
        };
        if (this.props.humanReadable && !this.state.hasFocus) {
            return formatFloat(this.value, {
                ...options,
                humanReadable: true,
                decimals: this.props.decimals,
            });
        } else {
            return formatFloat(this.value, {
                ...options,
                humanReadable: false,
            });
        }
    }
}

export const floatField = {
    component: FloatField,
    displayName: _t("Float"),
    supportedOptions: [
        {
            label: _t("Format number"),
            name: "enable_formatting",
            type: "boolean",
            help: _t(
                "Format the value according to your language setup - e.g. thousand separators, rounding, etc.",
            ),
            default: true,
        },
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
        {
            label: _t("Type"),
            name: "type",
            type: "string",
        },
        {
            label: _t("Step"),
            name: "step",
            type: "number",
        },
        {
            label: _t("User-friendly format"),
            name: "human_readable",
            type: "boolean",
            help: _t(
                "Use a human readable format (e.g.: 500G instead of 500,000,000,000).",
            ),
        },
        {
            label: _t("Hide trailing zeros"),
            name: "hide_trailing_zeros",
            type: "boolean",
            help: _t(
                "Hide zeros to the right of the last non-zero digit, e.g. 1.20 becomes 1.2",
            ),
        },
        {
            label: _t("Decimals"),
            name: "decimals",
            type: "number",
            default: 0,
            help: _t(
                "Use it with the 'User-friendly format' option to customize the formatting.",
            ),
        },
    ],
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
