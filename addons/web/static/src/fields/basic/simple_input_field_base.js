// @ts-check
/** @odoo-module native */

import { useInputField } from "@web/fields/input_field_hook";
import { standardFieldProps } from "@web/fields/standard_field_props";

import { TrimmingInputFieldBase } from "./trimming_input_field_base.js";

export class SimpleInputFieldBase extends TrimmingInputFieldBase {
    static props = {
        ...standardFieldProps,
        placeholder: { type: String, optional: true },
        required: { type: Boolean, optional: true },
    };

    setup() {
        useInputField({
            getValue: () => this.value,
            parse: (v) => this.parse(v),
        });
    }

    /** @returns {string} */
    get value() {
        return this.field.value || "";
    }
}
