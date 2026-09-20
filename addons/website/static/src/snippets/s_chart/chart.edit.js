/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Chart } from "@website/snippets/s_chart/chart";

const log = makeLogger("website.snippet.s_chart.edit");

const ChartEdit = (I) =>
    class extends I {
        setup() {
            super.setup();
            this.noAnimation = true;
        }

        start() {
            super.start();
            this.websiteEditService = this.services.website_edit;
            this.websiteEditService.callShared("builderOverlay", "refreshOverlays");
            log.lifecycle("start: overlays refreshed");
        }
    };

registry.category("public.interactions.edit").add("website.chart", {
    Interaction: Chart,
    mixin: ChartEdit,
});
