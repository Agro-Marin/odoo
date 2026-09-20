/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { MediaVideo } from "@website/interactions/video/media_video";

const log = makeLogger("website.interaction.media_video.edit");

export const MediaVideoEdit = (I) =>
    class extends I {
        destroy() {
            log.lifecycle("MediaVideoEdit destroy: clear children", () => ({
                hasEl: !!this.el,
            }));
            this.el?.replaceChildren();
        }
    };

registry.category("public.interactions.edit").add("website.media_video", {
    Interaction: MediaVideo,
    mixin: MediaVideoEdit,
});
