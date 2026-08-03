// @ts-check
/** @odoo-module native */

/**
 * @module @web/fields/relational/many2one_reference_integer/many2one_reference_integer_field
 */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { IntegerField } from "@web/fields/basic/integer/integer_field";

export class Many2OneReferenceIntegerField extends IntegerField {
    /** @returns {number|false} */
    get value() {
        const value = this.props.record.data[this.props.name];
        return value ? value.resId : false;
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
const many2oneReferenceIntegerField = {
    component: Many2OneReferenceIntegerField,
    displayName: _t("Many2OneReferenceInteger"),
    supportedTypes: ["many2one_reference"],
};

registerField("many2one_reference_integer", many2oneReferenceIntegerField);
