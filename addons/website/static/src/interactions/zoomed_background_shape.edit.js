/** @odoo-module native */
import { registry } from "@web/core/registry";

import { ZoomedBackgroundShape } from "./zoomed_background_shape.js";

const ZoomedBackgroundShapeEdit = (I) =>
    class extends I {
        shouldStop() {
            // Force restart.
            return true;
        }
    };

registry.category("public.interactions.edit").add("website.zoomed_background_shape", {
    Interaction: ZoomedBackgroundShape,
    mixin: ZoomedBackgroundShapeEdit,
});
