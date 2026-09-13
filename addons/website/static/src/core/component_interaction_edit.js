/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { PublicComponentInteraction } from "@web/public/public_component_interaction";

const log = makeLogger("website.edit.component_interaction");

const PublicComponentInteractionEdit = (I) =>
    class extends I {
        get Component() {
            const name = this.el.getAttribute("name");
            let C = registry.category("public_components.edit").get(name, false);
            if (!C) {
                log.logic(
                    "no edit component registered, fallback to public one, pointer events off",
                    () => ({
                        name,
                    }),
                );
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
