// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { SimpleInputFieldBase } from "@web/fields/basic/simple_input_field_base";
import { placeholderFieldOption } from "@web/fields/field_options";

export class EmailField extends SimpleInputFieldBase {
    static template = "web.EmailField";
}

/** @type {import("registries").FieldsRegistryItemShape} */
const emailField = {
    component: EmailField,
    displayName: _t("Email"),
    supportedOptions: [placeholderFieldOption()],
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

const formEmailField = {
    ...emailField,
    component: FormEmailField,
};

registerField({ name: "email", view: "form" }, formEmailField);
