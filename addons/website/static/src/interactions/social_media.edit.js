/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.social_media.edit");

export class SocialMediaEdit extends Interaction {
    static selector = ".s_social_media > :first-child";

    setup() {
        const endRender = log.perf(
            "SocialMediaEdit setup: render empty social media alert",
        );
        this.renderAt("website.empty_social_media_alert", {}, undefined, "afterend");
        endRender();
    }
}

registry.category("public.interactions.edit").add("website.social_media_edit", {
    Interaction: SocialMediaEdit,
});
