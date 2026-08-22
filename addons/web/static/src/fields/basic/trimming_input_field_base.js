// @ts-check
/** @odoo-module native */

import { FieldComponent } from "@web/fields/field_component";

export class TrimmingInputFieldBase extends FieldComponent {
    /** @returns {boolean} */
    get isTranslatable() {
        return this.field.definition.translate;
    }

    /** @returns {boolean} */
    get shouldTrim() {
        return Boolean(this.field.definition.trim);
    }

    /**
     * @param {string} value
     * @returns {string}
     */
    parse(value) {
        return this.shouldTrim ? value.trim() : value;
    }
}
