// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/float_time/float_time_field - Time duration input that stores hours as a float (e.g. 1.5 = 1h30) */

import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { formatFloatTime } from "@web/fields/formatters";
import { parseFloatTime } from "@web/fields/parsers";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { NumericInputFieldBase } from "../numeric_input_field_base.js";

export class FloatTimeField extends NumericInputFieldBase {
    static template = "web.FloatTimeField";
    static props = {
        ...standardFieldProps,
        inputType: { type: String, optional: true },
        displaySeconds: { type: Boolean, optional: true },
    };
    static defaultProps = {
        inputType: "text",
    };

    /** @param {string} v @returns {number} */
    parse(v) {
        return parseFloatTime(v);
    }

    /** @returns {string} float value formatted as HH:MM (or HH:MM:SS) */
    get formattedValue() {
        return formatFloatTime(this.props.record.data[this.props.name], {
            displaySeconds: this.props.displaySeconds,
        });
    }
}

export const floatTimeField = {
    component: FloatTimeField,
    displayName: _t("Time"),
    supportedOptions: [
        {
            label: _t("Display seconds"),
            // Match what extractProps reads and every arch passes (camelCase);
            // the snake_case name here was metadata-only and never functional.
            name: "displaySeconds",
            type: "boolean",
        },
        {
            label: _t("Type"),
            name: "type",
            type: "string",
            default: "text",
        },
    ],
    supportedTypes: ["float"],
    isEmpty: () => false,
    extractProps: ({ options }) => ({
        displaySeconds: options.displaySeconds,
        inputType: options.type,
    }),
};

registerField("float_time", floatTimeField);
