/** @odoo-module native */
import { registry } from "@web/core/registry";
import { FullScreenHeight } from "@website/interactions/full_screen_height";

const FullScreenHeightEdit = (I) =>
    class extends I {
        shouldStop() {
            return true;
        }
    };

registry.category("public.interactions.edit").add("website.full_screen_height", {
    Interaction: FullScreenHeight,
    mixin: FullScreenHeightEdit,
});
