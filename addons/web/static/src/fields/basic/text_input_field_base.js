// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/text_input_field_base - Abstract base class for text input fields with translation and dynamic placeholder support */

import { Component, useEffect, useExternalListener } from "@odoo/owl";
import { useDynamicPlaceholder } from "@web/fields/dynamic_placeholder_hook";

/**
 * Base class for text input fields (char, text/textarea, etc.).
 *
 * Provides shared infrastructure: isTranslatable getter, dynamic-placeholder
 * setup/open/validate handlers using this.inputEl as the target element, and
 * the caret-tracking onBlur.
 *
 * Subclasses must implement:
 *   - get inputEl — returns the native input/textarea DOM element
 */
export class TextInputFieldBase extends Component {
    /**
     * @abstract — override to return the native input/textarea element
     * @returns {HTMLInputElement | HTMLTextAreaElement | null | undefined}
     */
    get inputEl() {
        return null;
    }

    /** @returns {boolean} Whether this field supports translations */
    get isTranslatable() {
        return this.props.record.fields[this.props.name].translate;
    }

    /**
     * Wires the optional dynamic-placeholder feature and initializes the caret
     * position tracked for placeholder insertion. Must be called from setup().
     *
     * @param {import("@odoo/owl").Ref<HTMLInputElement | HTMLTextAreaElement>} ref
     *     Ref to the field's native input/textarea element.
     */
    setupDynamicPlaceholder(ref) {
        if (this.props.dynamicPlaceholder) {
            this.dynamicPlaceholder = useDynamicPlaceholder(ref);
            useExternalListener(document, "keydown", this.dynamicPlaceholder.onKeydown);
            useEffect(() =>
                this.dynamicPlaceholder.updateModel(
                    this.props.dynamicPlaceholderModelReferenceField,
                ),
            );
        }
        this.selectionStart = this.props.record.data[this.props.name]?.length || 0;
    }

    onBlur() {
        this.selectionStart = /** @type {HTMLInputElement | HTMLTextAreaElement} */ (
            this.inputEl
        ).selectionStart;
    }

    async onDynamicPlaceholderOpen() {
        await /** @type {any} */ (this).dynamicPlaceholder.open({
            validateCallback: this.onDynamicPlaceholderValidate.bind(this),
        });
    }

    /**
     * @param {string} chain - Dynamic placeholder field chain (e.g. "partner_id.name")
     * @param {string} [defaultValue] - Fallback value when the placeholder resolves to empty
     */
    async onDynamicPlaceholderValidate(chain, defaultValue) {
        this.dynamicPlaceholder.insert(chain, defaultValue, {
            rangeIndex: /** @type {any} */ (this).selectionStart,
        });
    }
}
