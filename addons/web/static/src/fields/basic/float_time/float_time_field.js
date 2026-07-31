// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float_time/float_time_field */

import { formatFloatTime } from "@web/core/formatters";
import { _t } from "@web/core/l10n/translation";
import { parseFloatTime } from "@web/core/parsers";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class FloatTimeField extends NumericInputFieldBase {
    static template = "web.FloatTimeField";
    static props = {
        ...standardFieldProps,
        displaySeconds: { type: Boolean, optional: true },
    };

    /**
     * @param {string} v
     * @returns {number}
     */
    parse(v) {
        return parseFloatTime(v);
    }

    /** @returns {string} */
    get formattedValue() {
        return formatFloatTime(this.props.record.data[this.props.name], {
            displaySeconds: this.props.displaySeconds,
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const floatTimeField = {
    component: FloatTimeField,
    displayName: _t("Time"),
    supportedOptions: [
        {
            label: _t("Display seconds"),
            name: "displaySeconds",
            type: "boolean",
        },
    ],
    supportedTypes: ["float"],
    isEmpty: () => false,
    extractProps: ({ options }) => ({
        displaySeconds: options.displaySeconds,
    }),
};

registerField("float_time", floatTimeField);
