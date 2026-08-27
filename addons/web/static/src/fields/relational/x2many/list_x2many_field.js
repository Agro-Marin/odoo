// @ts-check
/** @odoo-module native */

import { formatX2many } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ListX2ManyField extends FieldComponent {
    static template = "web.ListX2ManyField";
    static props = { ...standardFieldProps };

    /** @returns {string} */
    get formattedValue() {
        return formatX2many(this.field.value);
    }
}

const listX2ManyField = {
    component: ListX2ManyField,
    displayName: _t("Record Count"),
    supportedTypes: ["one2many", "many2many"],
    useSubView: false,
};

registerField({ name: "one2many", view: "list" }, listX2ManyField);
registerField({ name: "many2many", view: "list" }, listX2ManyField);
