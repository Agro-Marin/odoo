// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/trimming_input_field_base */

import { Component } from "@odoo/owl";

/**
 * The behaviour every single-line text-ish field shares: honour the field's
 * `trim` and expose whether it is translatable.
 *
 * Kept separate from {@link import("./text_input_field_base").TextInputFieldBase}
 * because the dynamic-placeholder host it adds is only usable by widgets whose
 * template wires it up. Fields that merely need `parse()` inherited the whole
 * placeholder surface -- including an `onBlur` that dereferences an `inputEl`
 * the subclass never overrode -- without ever calling `setupDynamicPlaceholder`.
 */
export class TrimmingInputFieldBase extends Component {
    /** @returns {boolean} */
    get isTranslatable() {
        return this.props.record.fields[this.props.name].translate;
    }

    /** @returns {boolean} */
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
}
