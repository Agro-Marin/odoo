// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/url/url_field */

import { _t } from "@web/core/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { TrimmingInputFieldBase } from "@web/fields/basic/trimming_input_field_base";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class UrlField extends TrimmingInputFieldBase {
    static template = "web.UrlField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        text: { type: String, optional: true },
        websitePath: { type: Boolean, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        useInputField({
            getValue: () => this.value,
            parse: (v) => this.parse(v),
        });
    }

    /** @returns {string} */
    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    /**
     * @returns {string}
     */
    get formattedHref() {
        let value = this.props.record.data[this.props.name];
        if (!value) {
            return "";
        }
        if (!this.props.websitePath) {
            const regex = /^((ftp|http)s?:\/\/|\/)/i;
            value = !regex.test(value) ? `http://${value}` : value;
        }
        return isSafeUrlScheme(value) ? value : "";
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const urlField = {
    component: UrlField,
    displayName: _t("URL"),
    supportedOptions: [
        {
            label: _t("Is a website path"),
            name: "website_path",
            type: "boolean",
            help: _t(
                "If True, the url will be used as it is, without any prefix added to it.",
            ),
        },
        {
            label: _t("Dynamic Placeholder"),
            name: "placeholder_field",
            type: "field",
            availableTypes: ["char"],
        },
    ],
    supportedTypes: ["char"],
    extractProps: ({ attrs, options, placeholder }, dynamicInfo) => ({
        placeholder,
        text: attrs.text,
        websitePath: options.website_path,
        required: dynamicInfo.required,
    }),
};

registerField("url", urlField);

class FormUrlField extends UrlField {
    static template = "web.FormUrlField";
}

export const formUrlField = {
    ...urlField,
    component: FormUrlField,
};

registerField({ name: "url", view: "form" }, formUrlField);
