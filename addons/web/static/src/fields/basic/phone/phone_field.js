// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { SimpleInputFieldBase } from "@web/fields/basic/simple_input_field_base";
import { placeholderFieldOption } from "@web/fields/field_options";

export class PhoneField extends SimpleInputFieldBase {
    static template = "web.PhoneField";
    /** @returns {string} */
    get phoneHref() {
        return `tel:${(this.field.value || "").replace(/\s+/g, "")}`;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const phoneField = {
    component: PhoneField,
    displayName: _t("Phone"),
    supportedOptions: [placeholderFieldOption()],
    supportedTypes: ["char"],
    extractProps: ({ placeholder }, dynamicInfo) => ({
        placeholder,
        required: dynamicInfo.required,
    }),
};

registerField("phone", phoneField);

class FormPhoneField extends PhoneField {
    static template = "web.FormPhoneField";
}

export const formPhoneField = {
    ...phoneField,
    component: FormPhoneField,
};

registerField({ name: "phone", view: "form" }, formPhoneField);
