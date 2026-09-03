/** @odoo-module native */
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("mrp_mo_components_kanban_on_mobile", {
    steps: () => [
        {
            content: "the components of an MO are cards, not an editable list",
            trigger:
                ".o_field_widget[name=move_raw_ids] .o_kanban_renderer .o_kanban_record",
            run: () => {},
        },
    ],
});
