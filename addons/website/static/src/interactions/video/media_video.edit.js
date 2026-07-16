/** @odoo-module native */
import { registry } from "@web/core/registry";

import { MediaVideo } from "./media_video.js";

export const MediaVideoEdit = (I) =>
    class extends I {
        destroy() {
            // Destroy video iframes so they are never saved in the DOM.
            this.el?.replaceChildren();
        }
    };

registry.category("public.interactions.edit").add("website.media_video", {
    Interaction: MediaVideo,
    mixin: MediaVideoEdit,
});
