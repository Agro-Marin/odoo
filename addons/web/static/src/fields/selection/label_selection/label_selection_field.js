// @ts-check
/** @odoo-module native */

import { formatSelection } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class LabelSelectionField extends FieldComponent {
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
const labelSelectionField = {
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
