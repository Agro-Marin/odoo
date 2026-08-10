// @ts-check
/** @odoo-module native */

/** @module @web/fields/selection/label_selection/label_selection_field */

import { Component } from "@odoo/owl";
import { formatSelection } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
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

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @returns {string} */
    get className() {
        return this.props.classesObj[this.field.value] || "primary";
    }
    /** @returns {string} */
    get string() {
        return formatSelection(this.field.value, {
            selection: Array.from(this.field.definition.selection),
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
