// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { IntegerField } from "@web/fields/basic/integer/integer_field";

export class Many2OneReferenceIntegerField extends IntegerField {
    /** @returns {number|false} */
    get value() {
        const value = this.field.value;
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
