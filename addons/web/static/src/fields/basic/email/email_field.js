// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/email/email_field */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { TrimmingInputFieldBase } from "@web/fields/basic/trimming_input_field_base";
import { useFieldHandle } from "@web/fields/field_handle";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class EmailField extends TrimmingInputFieldBase {
    static template = "web.EmailField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        this.field = useFieldHandle();
        useInputField({
            getValue: () => this.field.value || "",
            parse: (v) => this.parse(v),
        });
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const emailField = {
    component: EmailField,
    displayName: _t("Email"),
    supportedOptions: [
        {
            label: _t("Dynamic Placeholder"),
            name: "placeholder_field",
            type: "field",
            availableTypes: ["char"],
        },
    ],
    supportedTypes: ["char"],
    extractProps: ({ placeholder }, dynamicInfo) => ({
        placeholder,
        required: dynamicInfo.required,
    }),
};

registerField("email", emailField);

class FormEmailField extends EmailField {
    static template = "web.FormEmailField";
}

export const formEmailField = {
    ...emailField,
    component: FormEmailField,
};

registerField({ name: "email", view: "form" }, formEmailField);
