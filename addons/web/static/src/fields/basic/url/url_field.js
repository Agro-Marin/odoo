// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { SimpleInputFieldBase } from "@web/fields/basic/simple_input_field_base";
import { archAttribute, placeholderFieldOption } from "@web/fields/field_options";

export class UrlField extends SimpleInputFieldBase {
    static template = "web.UrlField";
    static props = {
        ...SimpleInputFieldBase.props,
        text: { type: String, optional: true },
        websitePath: { type: Boolean, optional: true },
    };

    /**
     * @returns {string}
     */
    get formattedHref() {
        let value = this.field.value;
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
        placeholderFieldOption(),
    ],
    supportedAttributes: [
        archAttribute("text", _t("Link text"), {
            help: _t("Fixed label shown instead of the URL itself."),
        }),
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

const formUrlField = {
    ...urlField,
    component: FormUrlField,
};

registerField({ name: "url", view: "form" }, formUrlField);
