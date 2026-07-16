/** @odoo-module native */
import { registry } from "@web/core/registry";

import { Chart } from "./chart.js";

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
        }
    };

registry.category("public.interactions.edit").add("website.chart", {
    Interaction: Chart,
    mixin: ChartEdit,
});
