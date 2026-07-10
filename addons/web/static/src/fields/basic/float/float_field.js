// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float/float_field - Numeric input field for Float columns with locale-aware formatting */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import {
    extractDigits,
    extractNumericOptions,
    isFalseEmpty,
} from "@web/fields/field_utils";
import { formatFloat } from "@web/fields/formatters";
import { parseFloat } from "@web/fields/parsers";
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

    /** @param {string} value @returns {number} */
    parse(value) {
        if (this.props.inputType === "number") {
            const parsed = Number(value);
            // A type=number input can still yield NaN (programmatic/garbage
            // value) or ±Infinity ("1e999" is accepted input text). Fall back
            // to the locale parser so it throws a ParseError and the field is
            // flagged invalid, instead of persisting NaN/Infinity (Infinity
            // JSON-serializes to null, silently unsetting the field).
            // (Number("") === 0, so empty input still resolves to 0 as before.)
            return Number.isFinite(parsed)
                ? parsed
                : parseFloat(value, { allowOperation: true });
        }
        return parseFloat(value, { allowOperation: true });
    }

    /**
     * @returns {string | number | false} ``false`` is returned when the
     *     ``!this.props.formatNumber`` branch passes through an unset value
     *     unchanged; consumers (the input element's ``value`` attribute and
     *     QWeb ``t-out``) already coerce ``false`` to an empty string.
     */
    get formattedValue() {
        if (this.props.inputType === "number" && !this.props.readonly) {
            // A `<input type="number">` cannot hold a locale-formatted string
            // (e.g. "0,00" in a comma-decimal locale makes the browser blank
            // the field), so emit the raw number. `false` (unset) becomes ""
            // while `0` is preserved rather than falling through to formatFloat.
            return this.value === false ? "" : this.value;
        }
        if (!this.props.formatNumber) {
            return this.value;
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
            name: "minDigits",
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
    extractProps: ({ attrs, options }) => ({
        ...extractNumericOptions({ options }),
        digits: extractDigits({ attrs, options }),
        minDigits: options.min_display_digits,
        trailingZeros: !options.hide_trailing_zeros,
    }),
};

registerField("float", floatField);
