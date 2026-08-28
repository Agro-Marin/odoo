// @ts-check
/** @odoo-module native */

import { useRef } from "@odoo/owl";
import { formatChar } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import {
    archAttribute,
    dynamicPlaceholderDependency,
    dynamicPlaceholderOptions,
    placeholderFieldOption,
} from "@web/fields/field_options";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { TranslationButton } from "@web/fields/translation_button";

import { TextInputFieldBase } from "../text_input_field_base.js";

export class CharField extends TextInputFieldBase {
    static template = "web.CharField";
    static components = {
        TranslationButton,
    };
    static props = {
        ...standardFieldProps,
        autocomplete: { type: String, optional: true },
        isPassword: { type: Boolean, optional: true },
        trim: { type: Boolean, optional: true },
        placeholder: { type: String, optional: true },
        dynamicPlaceholder: { type: Boolean, optional: true },
        dynamicPlaceholderModelReferenceField: { type: String, optional: true },
    };
    static defaultProps = { dynamicPlaceholder: false };

    /** @type {import("@odoo/owl").Ref<HTMLInputElement>} */
    input;

    /** @returns {HTMLInputElement | null} */
    get inputEl() {
        return /** @type {HTMLInputElement | null} */ (this.input.el);
    }

    setup() {
        useRenderCounter("fields.CharField");
        this.input = useRef("input");
        this.setupDynamicPlaceholder(this.input);
        useInputField({
            getValue: () => this.field.value || "",
            parse: (v) => this.parse(v),
        });
    }

    /**
     * A widget may state whether it trims, overriding what the field declares:
     * `char_emojis` must not, because a trailing space before an inserted emoji
     * is what the user is still typing. Left unset, the field's own `trim`
     * decides — which is the only thing that knows about the stored value.
     *
     * @returns {boolean}
     */
    get shouldTrim() {
        return (this.props.trim ?? super.shouldTrim) && !this.props.isPassword;
    }
    /** @returns {number | undefined} */
    get maxLength() {
        return this.field.definition.size;
    }
    /** @returns {string} */
    get formattedValue() {
        return formatChar(this.field.value, {
            isPassword: this.props.isPassword,
        });
    }
    /** @returns {boolean} */
    get hasDynamicPlaceholder() {
        return this.props.dynamicPlaceholder && !this.props.readonly;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const charField = {
    component: CharField,
    displayName: _t("Text"),
    supportedTypes: ["char", "text"],
    supportedOptions: [
        ...dynamicPlaceholderOptions(),
        placeholderFieldOption(["char", "text"]),
    ],
    supportedAttributes: [
        archAttribute("password", _t("Password"), {
            type: "boolean",
            help: _t("Render the input as `type=password`, masking what is typed."),
        }),
        archAttribute("autocomplete", _t("Autocomplete"), {
            help: _t(
                "Passed straight through to the input's `autocomplete` attribute.",
            ),
        }),
    ],
    fieldDependencies: dynamicPlaceholderDependency(),
    extractProps: ({ attrs, options, placeholder }) => ({
        isPassword: exprToBoolean(attrs.password),
        dynamicPlaceholder: options.dynamic_placeholder || false,
        dynamicPlaceholderModelReferenceField:
            options.dynamic_placeholder_model_reference_field || "",
        autocomplete: attrs.autocomplete,
        placeholder,
    }),
};

registerField("char", charField);
