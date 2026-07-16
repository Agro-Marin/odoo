// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/text/text_field - Multi-line textarea input field for Text columns */

import { useRef } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useAutoresize } from "@web/core/utils/dom/autoresize";
import { useSpellCheck } from "@web/core/utils/hooks";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";
import { registerField } from "@web/fields/_registry";
import { useInputField } from "@web/fields/input_field_hook";
import { parseInteger } from "@web/fields/parsers";
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
        useRenderCounter("fields.TextField");
        this.divRef = useRef("div");
        this.textareaRef = useRef("textarea");
        this.setupDynamicPlaceholder(this.textareaRef);
        useInputField({
            getValue: () => this.props.record.data[this.props.name] || "",
            refName: "textarea",
            parse: (v) => this.parse(v),
            preventLineBreaks: !this.props.lineBreaks,
        });
        useSpellCheck({ refName: "textarea" });

        useAutoresize(/** @type {any} */ (this.textareaRef), {
            minimumHeight: this.minimumHeight,
        });
    }

    /** @returns {boolean} */
    get shouldTrim() {
        return this.props.record.fields[this.props.name].trim;
    }

    /** @param {string} value @returns {string} */
    parse(value) {
        if (this.shouldTrim) {
            return value.trim();
        }
        return value;
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

export const textField = {
    component: TextField,
    displayName: _t("Multiline Text"),
    // ``html``, ``text`` and ``char`` all render in this widget's
    // textarea.  ``text`` is the canonical fit (multi-line free-form);
    // ``char`` is supported for short-string columns the arch-author
    // wants to give more visual room; ``html`` renders as plain text
    // (HTML markup is shown literally), useful for source-editing or
    // debug views.  Overlap with ``charField.supportedTypes`` is
    // intentional polymorphism — see the comment there.
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
            name: "placeholder_field",
            type: "field",
            // Mirrors ``charField``'s placeholder option: both ``char``
            // and ``text`` server types are valid sources for a
            // dynamic placeholder string.  The historical ``["char"]``
            // here was an asymmetry — text widgets render the same
            // placeholder string regardless of whether the source
            // field is char or text.
            availableTypes: ["char", "text"],
            help: _t(
                "Displays the value of the selected field as a textual hint. If the selected field is empty, the static placeholder attribute is displayed instead.",
            ),
        },
    ],
    extractProps: ({ attrs, options, placeholder }) => ({
        placeholder,
        dynamicPlaceholder: options?.dynamic_placeholder || false,
        dynamicPlaceholderModelReferenceField:
            options?.dynamic_placeholder_model_reference_field || "",
        rowCount: attrs.rows && parseInteger(attrs.rows),
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
