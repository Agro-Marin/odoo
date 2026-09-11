/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class DropdownEdit extends Interaction {
    static selector = "[data-bs-toggle=dropdown]";
    dynamicContent = {
        _root: {
            "t-att-data-bs-auto-close": () => "outside",
            "t-on-hidden.bs.dropdown": () => {
                const selection = this.el.ownerDocument.getSelection();
                if (
                    this.el.parentElement
                        ?.querySelector(".dropdown-menu")
                        ?.contains(selection.anchorNode)
                ) {
                    selection.empty();
                }
            },
        },
    };
}

registry.category("public.interactions.edit").add("website.dropdown_edit", {
    Interaction: DropdownEdit,
});
