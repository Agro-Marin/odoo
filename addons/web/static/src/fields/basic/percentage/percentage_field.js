// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/percentage/percentage_field */

import { formatPercentage } from "@web/core/formatters";
import { parsePercentage } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { Operation } from "@web/core/utils/operation";
import { registerField } from "@web/fields/_registry";
import { isFalseEmpty } from "@web/fields/field_utils";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class PercentageField extends NumericInputFieldBase {
    static template = "web.PercentageField";
    static props = {
        ...standardFieldProps,
        digits: { type: Array, optional: true },
    };

    /**
     * @param {string} v
     * @returns {number | Operation}
     */
    parse(v) {
        const parsed = parsePercentage(v, { allowOperation: true });
        if (parsed instanceof Operation) {
            if (parsed.operator === "+" || parsed.operator === "-") {
                return new Operation(parsed.operator, parsed.operand / 100);
            }
            return parsed;
        }
        return parsed;
    }

    /**
     * @returns {string}
     */
    get formattedValue() {
        return formatPercentage(this.value, {
            digits: this.props.digits,
            noSymbol: true,
            field: this.props.record.fields[this.props.name],
        });
    }

    /** @returns {string} */
    get formattedValueWithSymbol() {
        return formatPercentage(this.value, {
            digits: this.props.digits,
            field: this.props.record.fields[this.props.name],
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const percentageField = {
    component: PercentageField,
    displayName: _t("Percentage"),
    supportedOptions: [
        {
            label: _t("Digits"),
            name: "digits",
            type: "digits",
        },
    ],
    supportedTypes: ["float"],
    isEmpty: isFalseEmpty,
    extractProps: ({ attrs, options }) => ({
        digits: extractDigits({ attrs, options }),
    }),
};

registerField("percentage", percentageField);
