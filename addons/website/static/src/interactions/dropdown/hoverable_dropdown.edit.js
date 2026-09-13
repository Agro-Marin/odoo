/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { HoverableDropdown } from "@website/interactions/dropdown/hoverable_dropdown";

const log = makeLogger("website.interaction.hoverable_dropdown.edit");

const HoverableDropdownEdit = (I) =>
    class extends I {
        /**
         * @param {MouseEvent} ev
         * @param {HTMLElement} currentTargetEl
         */
        onMouseEnter(ev, currentTargetEl) {
            if (this.el.querySelector(".dropdown-toggle.show")) {
                log.logic(
                    "HoverableDropdownEdit onMouseEnter: a dropdown is open, skip",
                    () => ({
                        target: currentTargetEl.className,
                    }),
                );
                return;
            } else {
                super.onMouseEnter(ev, currentTargetEl);
            }
        }

        onMouseLeave() {}
    };

registry.category("public.interactions.edit").add("website.hoverable_dropdown", {
    Interaction: HoverableDropdown,
    mixin: HoverableDropdownEdit,
});
