/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many/x2many_field";

import { PredecessorIdsListRenderer } from "./predecessor_ids_list_renderer.js";

export class PredecessorIdsOne2ManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: PredecessorIdsListRenderer,
    };
}

export const predecessorIdsOne2ManyField = {
    ...x2ManyField,
    component: PredecessorIdsOne2ManyField,
};

registry.category("fields").add("predecessor_ids_one2many", predecessorIdsOne2ManyField);
