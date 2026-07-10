// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/x2many/list_x2many_field - Read-only list-view summary field for One2many and Many2many columns */

import { Component } from "@odoo/owl";
import { registerField } from "@web/fields/_registry";
import { formatX2many } from "@web/fields/formatters";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class ListX2ManyField extends Component {
    static template = "web.ListX2ManyField";
    static props = { ...standardFieldProps };

    /** @returns {string} Human-readable summary of the x2many relation (e.g. "3 records") */
    get formattedValue() {
        return formatX2many(this.props.record.data[this.props.name]);
    }
}

export const listX2ManyField = {
    component: ListX2ManyField,
    useSubView: false,
};

registerField({ name: "one2many", view: "list" }, listX2ManyField);
registerField({ name: "many2many", view: "list" }, listX2ManyField);
