// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float_factor/float_factor_field */

import { _t } from "@web/core/translation";
import { Operation } from "@web/core/utils/operation";
import { registerField } from "@web/fields/_registry";
import { FloatField, floatField } from "@web/fields/basic/float/float_field";

export class FloatFactorField extends FloatField {
    static props = {
        ...FloatField.props,
        factor: { type: Number, optional: true },
    };
    static defaultProps = {
        ...FloatField.defaultProps,
        factor: 1,
    };

    /** @returns {number} */
    get factor() {
        const factor = this.props.factor;
        if (!factor) {
            console.warn("float_factor: factor must be non-zero; falling back to 1");
            return 1;
        }
        return factor;
    }

    /**
     * @param {string} value
     * @returns {number|Operation}
     */
    parse(value) {
        const parsed = super.parse(value);
        if (parsed instanceof Operation) {
            if (parsed.operator === "+" || parsed.operator === "-") {
                return new Operation(parsed.operator, parsed.operand / this.factor);
            }
            return parsed;
        }
        return parsed / this.factor;
    }

    /** @returns {number|false} */
    get value() {
        const value = this.props.record.data[this.props.name];
        return value === false ? false : value * this.factor;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const floatFactorField = {
    ...floatField,
    component: FloatFactorField,
    supportedOptions: [
        ...floatField.supportedOptions,
        {
            label: _t("Factor"),
            name: "factor",
            type: "number",
        },
    ],
    extractProps: (fieldInfo, dynamicInfo) => ({
        .../** @type {any} */ (floatField.extractProps(fieldInfo, dynamicInfo)),
        factor: fieldInfo.options.factor,
    }),
};

registerField("float_factor", floatFactorField);
