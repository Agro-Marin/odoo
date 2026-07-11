// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/integer/integer_field - Numeric input field for Integer columns with locale-aware formatting */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { extractNumericOptions, isFalseEmpty } from "@web/fields/field_utils";
import { formatInteger } from "@web/fields/formatters";
import { parseInteger } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class IntegerField extends NumericInputFieldBase {
    static template = "web.IntegerField";
    static props = {
        ...standardFieldProps,
        formatNumber: { type: Boolean, optional: true },
        humanReadable: { type: Boolean, optional: true },
        decimals: { type: Number, optional: true },
        inputType: { type: String, optional: true },
        min: { type: Number, optional: true },
        max: { type: Number, optional: true },
        step: { type: Number, optional: true },
    };
    static defaultProps = {
        formatNumber: true,
        humanReadable: false,
        inputType: "text",
        decimals: 0,
    };

    /** @param {string} v @returns {number} */
    parse(v) {
        if (this.props.inputType === "number") {
            // A <input type="number"> value is always dot-decimal, regardless
            // of locale: feeding it to parseInteger would strip the dot as a
            // thousands separator in dot-thousands locales ("1.5" -> 15, a
            // silent 10x error — same guard as FloatField.parse). Validate the
            // already-numeric value with parseInteger's own rules instead.
            const parsed = Number(v);
            if (Number.isFinite(parsed)) {
                if (
                    !Number.isInteger(parsed) ||
                    parsed < -2147483648 ||
                    parsed > 2147483647
                ) {
                    throw new Error(`"${v}" is not a correct integer`);
                }
                return parsed;
            }
        }
        return parseInteger(v, { allowOperation: true });
    }

    /** @returns {string | number} */
    get formattedValue() {
        if (
            !this.props.formatNumber ||
            (!this.props.readonly && this.props.inputType === "number")
        ) {
            if (this.value === false) {
                return "";
            }
            return this.value;
        }
        if (this.props.humanReadable && !this.state.hasFocus) {
            return formatInteger(this.value, {
                humanReadable: true,
                decimals: this.props.decimals,
            });
        } else {
            return formatInteger(this.value, { humanReadable: false });
        }
    }
}

export const integerField = {
    component: IntegerField,
    displayName: _t("Integer"),
    supportedOptions: [
        {
            label: _t("Format number"),
            name: "enable_formatting",
            type: "boolean",
            help: _t(
                "Format the value according to your language setup - e.g. thousand separators, rounding, etc.",
            ),
            default: true,
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
            label: _t("Decimals"),
            name: "decimals",
            type: "number",
            default: 0,
            help: _t(
                "Use it with the 'User-friendly format' option to customize the formatting.",
            ),
        },
    ],
    supportedTypes: ["integer"],
    isEmpty: isFalseEmpty,
    extractProps: ({ options }) => ({
        ...extractNumericOptions({ options }),
        min: options.min,
        max: options.max,
    }),
};

registerField("integer", integerField);
