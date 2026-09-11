/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Animation } from "@website/interactions/animation";

const AnimationEdit = (I) =>
    class extends I {
        destroy() {
            this.el.classList.remove("o_animate_preview");
        }
    };

registry.category("public.interactions.edit").add("website.animation", {
    Interaction: Animation,
    mixin: AnimationEdit,
});
