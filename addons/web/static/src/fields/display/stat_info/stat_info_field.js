// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/stat_info/stat_info_field */

import { Component } from "@odoo/owl";
import { getFieldCodec } from "@web/core/field_codec";
import { _t } from "@web/core/translation";
import { extractDigits } from "@web/core/utils/format/digits";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class StatInfoField extends Component {
    static template = "web.StatInfoField";
    static props = {
        ...standardFieldProps,
        labelField: { type: String, optional: true },
        noLabel: { type: Boolean, optional: true },
        digits: { type: Array, optional: true },
        string: { type: String, optional: true },
    };

    /** @returns {string} */
    get formattedValue() {
        const field = this.props.record.fields[this.props.name];
        return getFieldCodec(field.type).format(
            this.props.record.data[this.props.name],
            {
                digits: this.props.digits,
                field,
            },
        );
    }
    /** @returns {string} */
    get label() {
        return this.props.labelField
            ? this.props.record.data[this.props.labelField]
            : this.props.string;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const statInfoField = {
    component: StatInfoField,
    displayName: _t("Stat Info"),
    supportedOptions: [
        {
            label: _t("Label field"),
            name: "label_field",
            type: "field",
            availableTypes: ["char"],
        },
        {
            label: _t("Digits"),
            name: "digits",
            type: "digits",
        },
    ],
    supportedTypes: ["float", "integer", "monetary", "char", "one2many", "many2one"],
    isEmpty: () => false,
    fieldDependencies: ({ options }) =>
        options.label_field
            ? [{ name: options.label_field, optional: true, readonly: true }]
            : [],
    extractProps: ({ attrs, options, string }) => ({
        digits: extractDigits({ attrs, options }),
        labelField: options.label_field,
        noLabel: exprToBoolean(attrs.nolabel),
        string,
    }),
};

registerField("statinfo", statInfoField);
