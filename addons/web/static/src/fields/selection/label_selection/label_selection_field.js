// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/label_selection/label_selection_field */

import { Component } from "@odoo/owl";
import { formatSelection } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class LabelSelectionField extends Component {
    static template = "web.LabelSelectionField";
    static props = {
        ...standardFieldProps,
        classesObj: { type: Object, optional: true },
    };
    static defaultProps = {
        classesObj: {},
    };

    /** @returns {string} */
    get className() {
        return (
            this.props.classesObj[this.props.record.data[this.props.name]] || "primary"
        );
    }
    /** @returns {string} */
    get string() {
        return formatSelection(this.props.record.data[this.props.name], {
            selection: Array.from(this.props.record.fields[this.props.name].selection),
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const labelSelectionField = {
    component: LabelSelectionField,
    displayName: _t("Label Selection"),
    supportedOptions: [
        {
            label: _t("Classes"),
            name: "classes",
            type: "string",
        },
    ],
    supportedTypes: ["selection"],
    extractProps: ({ options }) => ({
        classesObj: options.classes,
    }),
};

registerField("label_selection", labelSelectionField);
