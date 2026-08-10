// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/text/text_field */

import { useRef } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
import { useSpellCheck } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { useFieldHandle } from "@web/fields/field_handle";
import { parseDimensionAttr } from "@web/fields/field_utils";
import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { TranslationButton } from "@web/fields/translation_button";

import { TextInputFieldBase } from "../text_input_field_base.js";

export class TextField extends TextInputFieldBase {
    static template = "web.TextField";
    static components = {
        TranslationButton,
    };
    static props = {
        ...standardFieldProps,
        lineBreaks: { type: Boolean, optional: true },
        placeholder: { type: String, optional: true },
        dynamicPlaceholder: { type: Boolean, optional: true },
        dynamicPlaceholderModelReferenceField: { type: String, optional: true },
        rowCount: { type: Number, optional: true },
    };
    static defaultProps = {
        lineBreaks: true,
        dynamicPlaceholder: false,
        rowCount: 2,
    };

    /** @type {import("@odoo/owl").Ref<HTMLTextAreaElement>} */
    textareaRef;
    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    divRef;

    /** @returns {HTMLTextAreaElement | null} */
    get inputEl() {
        return /** @type {HTMLTextAreaElement | null} */ (this.textareaRef.el);
    }

    setup() {
        this.field = useFieldHandle();
        useRenderCounter("fields.TextField");
        this.divRef = useRef("div");
        this.textareaRef = useRef("textarea");
        this.setupDynamicPlaceholder(this.textareaRef);
        useInputField({
            getValue: () => this.field.value || "",
            refName: "textarea",
            parse: (v) => this.parse(v),
            preventLineBreaks: !this.props.lineBreaks,
        });
        useSpellCheck({ refName: "textarea" });

        useAutoresize(/** @type {any} */ (this.textareaRef), {
            minimumHeight: this.minimumHeight,
        });
    }

    /** @returns {number} */
    get minimumHeight() {
        return this.props.lineBreaks ? 50 : 0;
    }
    /** @returns {number} */
    get rowCount() {
        return this.props.lineBreaks ? this.props.rowCount : 1;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const textField = {
    component: TextField,
    displayName: _t("Multiline Text"),
    supportedTypes: ["html", "text", "char"],
    supportedOptions: [
        {
            label: _t("Enable line breaks"),
            name: "line_breaks",
            type: "boolean",
            default: true,
        },
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
        placeholder,
        dynamicPlaceholder: options?.dynamic_placeholder || false,
        dynamicPlaceholderModelReferenceField:
            options?.dynamic_placeholder_model_reference_field || "",
        rowCount: parseDimensionAttr(attrs.rows),
        lineBreaks:
            options?.line_breaks !== undefined ? Boolean(options.line_breaks) : true,
    }),
};

registerField("text", textField);

export class ListTextField extends TextField {
    static defaultProps = {
        ...super.defaultProps,
        rowCount: 1,
    };

    // @ts-ignore — narrower return type is intentional for list view
    /** @returns {number} */
    get minimumHeight() {
        return 0;
    }
    /** @returns {number} */
    get rowCount() {
        return this.props.rowCount;
    }
}

export const listTextField = {
    ...textField,
    component: ListTextField,
};

registerField({ name: "text", view: "list" }, listTextField);
