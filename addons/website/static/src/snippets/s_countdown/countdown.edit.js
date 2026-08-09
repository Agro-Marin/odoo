/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Countdown } from "@website/snippets/s_countdown/countdown";

const CountdownEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.websiteEditService = this.services.website_edit;
            this.websiteEditService.callShared("builderOverlay", "refreshOverlays");
        }
        get shouldHideCountdown() {
            return false;
        }
        handleEndCountdownAction() {}
    };

registry.category("public.interactions.edit").add("website.countdown", {
    Interaction: Countdown,
    mixin: CountdownEdit,
});
