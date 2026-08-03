// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/phone/phone_field */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { TrimmingInputFieldBase } from "@web/fields/basic/trimming_input_field_base";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PhoneField extends TrimmingInputFieldBase {
    static template = "web.PhoneField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        useInputField({
            getValue: () => this.props.record.data[this.props.name] || "",
            parse: (v) => this.parse(v),
        });
    }
    /** @returns {string} */
    get phoneHref() {
        return `tel:${(this.props.record.data[this.props.name] || "").replace(/\s+/g, "")}`;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const phoneField = {
    component: PhoneField,
    displayName: _t("Phone"),
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

registerField("phone", phoneField);

class FormPhoneField extends PhoneField {
    static template = "web.FormPhoneField";
}

export const formPhoneField = {
    ...phoneField,
    component: FormPhoneField,
};

registerField({ name: "phone", view: "form" }, formPhoneField);
