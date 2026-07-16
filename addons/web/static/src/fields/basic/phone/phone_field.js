// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/phone/phone_field - Phone number input field with tel: link in readonly mode */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registerField } from "@web/fields/_registry";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class PhoneField extends Component {
    static template = "web.PhoneField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        useInputField({
            getValue: () => this.props.record.data[this.props.name] || "",
        });
    }
    /** @returns {string} tel: URI with whitespace stripped */
    get phoneHref() {
        return `tel:${(this.props.record.data[this.props.name] || "").replace(/\s+/g, "")}`;
    }
}

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
        // Matches EmailField/UrlField: without this a required phone never got
        // the t-att-required HTML attribute (declared+extracted here, bound in
        // the template).
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
