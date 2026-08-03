/** @odoo-module native */
import { omit } from "@web/core/utils/collections/objects";
import { Many2OneField } from "@web/fields/relational/many2one";

import { Component, toRaw } from "@odoo/owl";

export class DocumentsDetailsMany2OneField extends Component {
    static components = { Many2OneField };
    static props = {
        ...Many2OneField.props,
        readonlyPlaceholder: Many2OneField.props.placeholder,
    };
    static template = "documents.DocumentsDetailsMany2One";

    get value() {
        return toRaw(this.props.record.data[this.props.name]);
    }

    get fieldProps() {
        return omit(this.props, "readonlyPlaceholder");
    }
}
