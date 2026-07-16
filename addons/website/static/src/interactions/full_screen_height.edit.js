/** @odoo-module native */
import { registry } from "@web/core/registry";

import { FullScreenHeight } from "./full_screen_height.js";

const FullScreenHeightEdit = (I) =>
    class extends I {
        shouldStop() {
            // Force restart on refresh.
            return true;
        }
    };

registry.category("public.interactions.edit").add("website.full_screen_height", {
    Interaction: FullScreenHeight,
    mixin: FullScreenHeightEdit,
});
