// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/char/char_field */

import { useRef } from "@odoo/owl";
import { formatChar } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { exprToBoolean } from "@web/core/utils/format/strings";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
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
        placeholder: { type: String, optional: true },
        dynamicPlaceholder: { type: Boolean, optional: true },
        dynamicPlaceholderModelReferenceField: { type: String, optional: true },
    };
    static defaultProps = { dynamicPlaceholder: false };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

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

    /** @returns {boolean} */
    get shouldTrim() {
        return super.shouldTrim && !this.props.isPassword;
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
        {
            label: _t("Dynamic Placeholder"),
            name: "dynamic_placeholder",
            type: "boolean",
            help: _t(
                "Offer a picker that inserts a {{object.field}} expression into the text.",
            ),
        },
        {
            label: _t("Dynamic Placeholder model reference"),
            name: "dynamic_placeholder_model_reference_field",
            type: "field",
            availableTypes: ["char"],
            help: _t("Field holding the model name whose fields the picker offers."),
        },
        {
            label: _t("Dynamic Placeholder"),
            name: "placeholder_field",
            type: "field",
            availableTypes: ["char", "text"],
            help: _t(
                "Displays the value of the selected field as a textual hint. If the selected field is empty, the static placeholder attribute is displayed instead.",
            ),
        },
    ],
    // `useDynamicPlaceholder.updateModel` reads this out of `record.data` to
    // decide which model's fields the picker offers, so a view that names the
    // option but not the field silently fell back to `record.data.model`.
    fieldDependencies: ({ options }) =>
        options.dynamic_placeholder_model_reference_field
            ? [
                  {
                      name: options.dynamic_placeholder_model_reference_field,
                      optional: true,
                      readonly: true,
                  },
              ]
            : [],
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
