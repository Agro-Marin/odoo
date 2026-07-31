// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/text_input_field_base */

import { Component, useEffect, useExternalListener } from "@odoo/owl";
import { useDynamicPlaceholder } from "@web/fields/dynamic_placeholder_hook";

export class TextInputFieldBase extends Component {
    /**
     * @type {any}
     */
    dynamicPlaceholder;

    /**
     * @abstract
     * @returns {HTMLInputElement | HTMLTextAreaElement | null | undefined}
     */
    get inputEl() {
        return null;
    }

    /** @returns {boolean} */
    get isTranslatable() {
        return this.props.record.fields[this.props.name].translate;
    }

    /**
     * @returns {boolean}
     */
    get shouldTrim() {
        return Boolean(this.props.record.fields[this.props.name].trim);
    }

    /**
     * @param {string} value
     * @returns {string}
     */
    parse(value) {
        return this.shouldTrim ? value.trim() : value;
    }

    /**
     * @param {import("@odoo/owl").Ref<HTMLInputElement | HTMLTextAreaElement>} ref
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
     * @param {string} chain
     * @param {string} [defaultValue]
     */
    async onDynamicPlaceholderValidate(chain, defaultValue) {
        this.dynamicPlaceholder.insert(chain, defaultValue, {
            rangeIndex: /** @type {any} */ (this).selectionStart,
        });
    }
}
