// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float_factor/float_factor_field - Float field that applies a multiplication factor for display and storage */

import { _t } from "@web/core/l10n/translation";
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

    /** @returns {number} the multiplication factor, guarded against 0 */
    get factor() {
        const factor = this.props.factor;
        if (!factor) {
            console.warn("float_factor: factor must be non-zero; falling back to 1");
            return 1;
        }
        return factor;
    }

    /**
     * @param {string} value - user input to parse
     * @returns {number} parsed float divided by the factor
     */
    parse(value) {
        return super.parse(value) / this.factor;
    }

    /** @returns {number|false} stored value multiplied by the factor, or false when unset */
    get value() {
        const value = this.props.record.data[this.props.name];
        return value === false ? false : value * this.factor;
    }
}

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
    extractProps({ options }) {
        const props = /** @type {any} */ (
            floatField.extractProps(.../** @type {any} */ (arguments))
        );
        props.factor = options.factor;
        return props;
    },
};

registerField("float_factor", floatFactorField);
