// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { registerField } from "@web/fields/_registry";
import {
    computeM2OProps,
    KanbanMany2One,
} from "@web/fields/relational/many2one/many2one";
import {
    buildM2OFieldDescription,
    Many2OneField,
} from "@web/fields/relational/many2one/many2one_field";

export class KanbanMany2OneAvatarField extends Component {
    static template = "web.KanbanMany2OneAvatarField";
    static components = { KanbanMany2One };
    static props = { ...Many2OneField.props };

    /** @returns {Object} */
    get m2oProps() {
        return computeM2OProps(this.props);
    }
}

registerField(
    { name: "many2one_avatar", view: "kanban" },
    {
        ...buildM2OFieldDescription(KanbanMany2OneAvatarField),
        additionalClasses: ["o_field_many2one_avatar_kanban"],
        interactiveOutsideEdition: true,
    },
);
