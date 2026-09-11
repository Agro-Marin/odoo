/** @odoo-module native */
import { registry } from "@web/core/registry";
import { MediaVideo } from "@website/interactions/video/media_video";

export const MediaVideoEdit = (I) =>
    class extends I {
        destroy() {
            this.el?.replaceChildren();
        }
    };

registry.category("public.interactions.edit").add("website.media_video", {
    Interaction: MediaVideo,
    mixin: MediaVideoEdit,
});
