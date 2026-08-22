// @ts-check
/** @odoo-module native */

import { useEffect, useExternalListener } from "@odoo/owl";
import { useDynamicPlaceholder } from "@web/fields/dynamic_placeholder_hook";

import { TrimmingInputFieldBase } from "./trimming_input_field_base.js";

export class TextInputFieldBase extends TrimmingInputFieldBase {
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

    /**
     * @param {import("@odoo/owl").Ref<HTMLInputElement | HTMLTextAreaElement>} ref
     */
    setupDynamicPlaceholder(ref) {
        if (this.props.dynamicPlaceholder) {
            this.dynamicPlaceholder = useDynamicPlaceholder(ref);
            useExternalListener(document, "keydown", this.dynamicPlaceholder.onKeydown);
            useEffect(
                () =>
                    this.dynamicPlaceholder.updateModel(
                        this.props.dynamicPlaceholderModelReferenceField,
                    ),
                () => [
                    this.props.dynamicPlaceholderModelReferenceField,
                    this.props.record.data[
                        this.props.dynamicPlaceholderModelReferenceField
                    ],
                    this.props.record.data.render_model,
                    this.props.record.data.model,
                ],
            );
        }
        this.selectionStart = this.field.value?.length || 0;
    }

    onBlur() {
        this.selectionStart = /** @type {HTMLInputElement | HTMLTextAreaElement} */ (
            this.inputEl
        ).selectionStart;
    }

    onDynamicPlaceholderOpen() {
        /** @type {any} */ (this).dynamicPlaceholder.open({
            validateCallback: this.onDynamicPlaceholderValidate.bind(this),
            // Without this the popover closes leaving the focus on the button
            // that opened it, where the `#` trigger returns it to the input.
            closeCallback: () => this.inputEl?.focus(),
        });
    }

    /**
     * @param {string} chain
     * @param {string} [defaultValue]
     * @param {string} [fieldType]
     */
    async onDynamicPlaceholderValidate(chain, defaultValue, fieldType) {
        await this.dynamicPlaceholder.insert(chain, defaultValue, {
            fieldType,
            rangeIndex: /** @type {any} */ (this).selectionStart,
        });
    }
}
