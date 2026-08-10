// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/x2many/list_x2many_field */

import { Component } from "@odoo/owl";
import { formatX2many } from "@web/core/formatters";
import { registerField } from "@web/fields/_registry";
import { fieldHandle } from "@web/fields/field_handle";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ListX2ManyField extends Component {
    static template = "web.ListX2ManyField";
    static props = { ...standardFieldProps };

    /** @returns {import("@web/fields/field_handle").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }

    /** @returns {string} */
    get formattedValue() {
        return formatX2many(this.field.value);
    }
}

export const listX2ManyField = {
    component: ListX2ManyField,
    supportedTypes: ["one2many", "many2many"],
    useSubView: false,
};

registerField({ name: "one2many", view: "list" }, listX2ManyField);
registerField({ name: "many2many", view: "list" }, listX2ManyField);
