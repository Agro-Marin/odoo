/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Animation } from "@website/interactions/animation";

const log = makeLogger("website.interaction.animation.edit");

const AnimationEdit = (I) =>
    class extends I {
        destroy() {
            log.lifecycle("AnimationEdit destroy", () => ({
                className: this.el.className,
            }));
            this.el.classList.remove("o_animate_preview");
        }
    };

registry.category("public.interactions.edit").add("website.animation", {
    Interaction: Animation,
    mixin: AnimationEdit,
});
