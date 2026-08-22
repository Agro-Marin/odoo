// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanIconField extends FieldComponent {
    static template = "web.BooleanIconField";
    static props = {
        ...standardFieldProps,
        icon: { type: String, optional: true },
        label: { type: String, optional: true },
    };
    static defaultProps = {
        icon: "fa-regular fa-square-check",
    };

    update() {
        if (this.props.readonly) {
            return;
        }
        this.field.update(!this.field.value);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const booleanIconField = {
    component: BooleanIconField,
    displayName: _t("Boolean Icon"),
    interactiveOutsideEdition: true,
    supportedOptions: [
        {
            label: _t("Icon"),
            name: "icon",
            type: "string",
        },
    ],
    supportedTypes: ["boolean"],
    extractProps: ({ options, string }, dynamicInfo) => ({
        icon: options.icon,
        label: string,
    }),
};

registerField("boolean_icon", booleanIconField);
