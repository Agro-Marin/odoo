// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/boolean_icon/boolean_icon_field */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class BooleanIconField extends Component {
    static template = "web.BooleanIconField";
    static props = {
        ...standardFieldProps,
        icon: { type: String, optional: true },
        label: { type: String, optional: true },
    };
    static defaultProps = {
        icon: "fa-regular fa-square-check",
    };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

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
