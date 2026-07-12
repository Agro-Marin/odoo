// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/url/url_field - URL input field with clickable hyperlink in readonly mode */

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { isSafeUrlScheme } from "@web/core/utils/urls";
import { registerField } from "@web/fields/_registry";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class UrlField extends Component {
    static template = "web.UrlField";
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        text: { type: String, optional: true },
        websitePath: { type: Boolean, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        useInputField({ getValue: () => this.value });
    }

    /** @returns {string} raw field value or empty string */
    get value() {
        return this.props.record.data[this.props.name] || "";
    }

    /**
     * @returns {string} a safe hyperlink target: the value prefixed with
     * http:// when it carries no protocol, restricted to safe schemes. Unsafe
     * values (javascript:/data:/vbscript:, protocol-relative //host) are
     * dropped so they never reach the rendered t-att-href.
     */
    get formattedHref() {
        let value = this.props.record.data[this.props.name];
        if (!value) {
            return "";
        }
        if (!this.props.websitePath) {
            // Prefix "http://" unless the value already carries a full scheme
            // (http(s)://, ftp(s)://) or is a site-relative path (/...). The
            // scheme branch requires BOTH slashes so a single-slash typo like
            // "http:/x" is treated as scheme-less and prefixed, not left as a
            // dead link.
            const regex = /^((ftp|http)s?:\/\/|\/)/i;
            value = !regex.test(value) ? `http://${value}` : value;
        }
        return isSafeUrlScheme(value) ? value : "";
    }
}

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
