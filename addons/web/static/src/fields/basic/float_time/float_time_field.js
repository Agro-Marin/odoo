// @ts-check
/** @odoo-module native */

import { formatFloatTime } from "@web/core/formatters";
import { parseFloatTime } from "@web/core/parsers";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
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
        return formatFloatTime(this.field.value, {
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
            name: "display_seconds",
            type: "boolean",
        },
    ],
    supportedTypes: ["float"],
    isEmpty: () => false,
    extractProps: ({ options }) => ({
        displaySeconds: exprToBoolean(
            options.display_seconds ?? options.displaySeconds ?? false,
        ),
    }),
};

registerField("float_time", floatTimeField);
