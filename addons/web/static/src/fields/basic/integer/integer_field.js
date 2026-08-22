// @ts-check
/** @odoo-module native */

import { formatInteger } from "@web/core/formatters";
import { parseInteger } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import {
    enableFormattingOption,
    humanReadableOptions,
    numericInputOptions,
} from "@web/fields/field_options";
import { extractNumericOptions, isFalseEmpty } from "@web/fields/field_utils";
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

    /**
     * @param {string} v
     * @returns {number}
     */
    parse(v) {
        return this.parseNumericInput(
            v,
            (val) => parseInteger(val, { allowOperation: true }),
            { integer: true },
        );
    }

    /**
     * @param {boolean} humanReadable
     * @returns {string}
     */
    formatValue(humanReadable) {
        return formatInteger(this.value, {
            humanReadable,
            ...(humanReadable ? { decimals: this.props.decimals } : {}),
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const integerField = {
    component: IntegerField,
    displayName: _t("Integer"),
    supportedOptions: [
        enableFormattingOption(),
        ...numericInputOptions(),
        {
            label: _t("Minimum"),
            name: "min",
            type: "number",
            help: _t(
                "Lower bound of the number input. Only applies with Type 'number'.",
            ),
        },
        {
            label: _t("Maximum"),
            name: "max",
            type: "number",
            help: _t(
                "Upper bound of the number input. Only applies with Type 'number'.",
            ),
        },
        ...humanReadableOptions(),
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
