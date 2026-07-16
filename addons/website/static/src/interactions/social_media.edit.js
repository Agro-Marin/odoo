/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class SocialMediaEdit extends Interaction {
    static selector = ".s_social_media > :first-child";

    setup() {
        this.renderAt("website.empty_social_media_alert", {}, undefined, "afterend");
    }
}

registry.category("public.interactions.edit").add("website.social_media_edit", {
    Interaction: SocialMediaEdit,
});
