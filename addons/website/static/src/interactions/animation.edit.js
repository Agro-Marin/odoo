/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Animation } from "./animation.js";

const AnimationEdit = (I) =>
    class extends I {
        destroy() {
            // We remove the "o_animate_preview" class here because it is added
            // when an animation is selected in the options, and the "Animation"
            // interaction considers it as part of the initial state. We remove
            // it here because otherwise it is added back when exiting edit
            // mode.
            this.el.classList.remove("o_animate_preview");
        }
    };

registry.category("public.interactions.edit").add("website.animation", {
    Interaction: Animation,
    mixin: AnimationEdit,
});
