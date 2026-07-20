/** @odoo-module native */
import { registry } from "@web/core/registry";
import { X2ManyField, x2ManyField } from "@web/fields/relational/x2many/x2many_field";

import { SlideCategoryListRenderer } from "./slide_category_list_renderer.js";

class SlideCategoryOneToManyField extends X2ManyField {
    static components = {
        ...X2ManyField.components,
        ListRenderer: SlideCategoryListRenderer,
    };
    static defaultProps = {
        ...X2ManyField.defaultProps,
        editable: "bottom",
    };
    setup() {
        super.setup();
        this.canOpenRecord = true;
    }
}

registry.category("fields").add("slide_category_one2many", {
    ...x2ManyField,
    component: SlideCategoryOneToManyField,
    additionalClasses: [...(x2ManyField.additionalClasses || []), "o_field_one2many"],
});
