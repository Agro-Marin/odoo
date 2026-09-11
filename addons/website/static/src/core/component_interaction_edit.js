/** @odoo-module native */
import { registry } from "@web/core/registry";
import { PublicComponentInteraction } from "@web/public/public_component_interaction";

const PublicComponentInteractionEdit = (I) =>
    class extends I {
        get Component() {
            const name = this.el.getAttribute("name");
            let C = registry.category("public_components.edit").get(name, false);
            if (!C) {
                C = super.Component;
                this.el.style.pointerEvents = "none";
            }
            return C;
        }
    };

registry.category("public.interactions.edit").add("public_components", {
    Interaction: PublicComponentInteraction,
    mixin: PublicComponentInteractionEdit,
});
