/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Countdown } from "@website/snippets/s_countdown/countdown";

const log = makeLogger("website.snippet.s_countdown.edit");

const CountdownEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.websiteEditService = this.services.website_edit;
            this.websiteEditService.callShared("builderOverlay", "refreshOverlays");
            log.lifecycle("setup: overlays refreshed");
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
