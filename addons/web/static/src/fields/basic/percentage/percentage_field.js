// @ts-check
/** @odoo-module native */

import { formatPercentage } from "@web/core/formatters";
import { parsePercentage } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { Operation } from "@web/core/utils/operation";
import { registerField } from "@web/fields/_registry";
import { digitsAttribute } from "@web/fields/field_options";
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
        // `parsePercentage` scales a plain number but hands an Operation back
        // unscaled, so only an ADDITIVE operand needs the /100: `*2` and `/2`
        // already act correctly on the stored fraction.
        if (parsed instanceof Operation && ["+", "-"].includes(parsed.operator)) {
            return new Operation(parsed.operator, parsed.operand / 100);
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
            field: this.field.definition,
        });
    }

    /** @returns {string} */
    get formattedValueWithSymbol() {
        return formatPercentage(this.value, {
            digits: this.props.digits,
            field: this.field.definition,
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const percentageField = {
    component: PercentageField,
    displayName: _t("Percentage"),
    supportedOptions: [
        {
            label: _t("Digits"),
            name: "digits",
            type: "digits",
        },
    ],
    supportedAttributes: [digitsAttribute()],
    supportedTypes: ["float"],
    isEmpty: isFalseEmpty,
    extractProps: ({ attrs, options }) => ({
        digits: extractDigits({ attrs, options }),
    }),
};

registerField("percentage", percentageField);
