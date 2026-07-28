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
     * Dynamic-placeholder helper, set by setupDynamicPlaceholder() when the
     * feature is enabled. Declared on the base class so subclasses don't
     * shadow it (TS2612).
     * @type {any}
     */
    dynamicPlaceholder;

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
     * Whether user input must be trimmed before it reaches the record.
     *
     * ``Char.trim`` defaults to ``True`` and the ORM documents the trim as
     * client-enforced: "The web client trims user input during in write/create
     * flows in UI. The server trims values during import (in ``base_import``)"
     * (``odoo/orm/fields/textual.py``). Nothing strips the value on
     * ``write``/``create`` — verified against Postgres, ``web_save`` stores
     * "  x  " verbatim on a ``trim=True`` column. So a widget that skips this
     * writes untrimmed data for a field declared trimmed, and the same column
     * ends up with different content depending on which widget edited it.
     *
     * @returns {boolean}
     */
    get shouldTrim() {
        return this.props.record.fields[this.props.name].trim;
    }

    /**
     * Input parser shared by every widget backed by a textual column. Wire it
     * through ``useInputField({ parse })`` — a widget that omits it opts out of
     * the trim contract above.
     *
     * @param {string} value
     * @returns {string}
     */
    parse(value) {
        return this.shouldTrim ? value.trim() : value;
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
