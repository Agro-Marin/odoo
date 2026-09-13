/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.dropdown.edit");

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
                    log.logic(
                        "DropdownEdit hidden: clear selection inside menu",
                        () => ({
                            toggle: this.el.className,
                        }),
                    );
                    selection.empty();
                }
            },
        },
    };
}

registry.category("public.interactions.edit").add("website.dropdown_edit", {
    Interaction: DropdownEdit,
});
