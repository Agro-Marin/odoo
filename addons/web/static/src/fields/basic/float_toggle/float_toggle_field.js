// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float_toggle/float_toggle_field */

import { Component } from "@odoo/owl";
import { formatFloatFactor } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class FloatToggleField extends Component {
    static template = "web.FloatToggleField";
    static props = {
        ...standardFieldProps,
        digits: { type: Array, optional: true },
        range: { type: Array, optional: true },
        factor: { type: Number, optional: true },
        disableReadOnly: { type: Boolean, optional: true },
    };
    static defaultProps = {
        range: [0.0, 0.5, 1.0],
        factor: 1,
        disableReadOnly: false,
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    onChange() {
        const range = this.range;
        const current = this.field.value * this.factor;
        const EPSILON = 1e-6;
        let currentIndex = range.findIndex(
            (/** @type {number} */ v) => Math.abs(v - current) < EPSILON,
        );
        currentIndex++;
        if (currentIndex > range.length - 1) {
            currentIndex = 0;
        }
        this.field.update(range[currentIndex] / this.factor);
    }

    /**
     * The `range` option is arbitrary arch input. An empty or non-numeric one
     * used to make `range[currentIndex]` undefined and write NaN to the record.
     *
     * @returns {number[]}
     */
    get range() {
        const range = this.props.range;
        const isUsable =
            Array.isArray(range) &&
            range.length > 0 &&
            range.every((v) => Number.isFinite(v));
        if (!isUsable) {
            console.warn(
                "float_toggle: 'range' must be a non-empty list of numbers; " +
                    "falling back to the default",
            );
            return /** @type {number[]} */ (
                /** @type {any} */ (FloatToggleField).defaultProps.range
            );
        }
        return range;
    }

    /** @returns {number} */
    get factor() {
        const factor = this.props.factor;
        if (!Number.isFinite(factor) || factor === 0) {
            console.warn("float_toggle: factor must be a non-zero number; using 1");
            return 1;
        }
        return factor;
    }

    /** @returns {string} */
    get formattedValue() {
        return formatFloatFactor(this.field.value, {
            digits: this.props.digits,
            factor: this.factor,
            field: this.field.definition,
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const floatToggleField = {
    component: FloatToggleField,
    supportedOptions: [
        {
            label: _t("Digits"),
            name: "digits",
            type: "digits",
        },
        {
            label: _t("Range"),
            name: "range",
            type: "string",
        },
        {
            label: _t("Factor"),
            name: "factor",
            type: "number",
        },
        {
            label: _t("Disable readonly"),
            name: "force_button",
            type: "boolean",
        },
    ],
    supportedTypes: ["float"],
    isEmpty: () => false,
    extractProps: ({ attrs, options }) => ({
        digits: extractDigits({ attrs, options }),
        range: options.range,
        factor: options.factor,
        disableReadOnly: options.force_button || false,
    }),
};

registerField("float_toggle", floatToggleField);
