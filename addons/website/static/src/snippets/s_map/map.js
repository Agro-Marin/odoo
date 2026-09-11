/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { generateGMapIframe, generateGMapLink } from "@website/js/utils";

export class Map extends Interaction {
    static selector = ".s_map";

    start() {
        if (!this.el.querySelector(".s_map_embedded")) {
            const dataset = this.el.dataset;
            if (dataset.mapAddress) {
                const iframeEl = generateGMapIframe();
                this.el.querySelector(".s_map_color_filter").before(iframeEl);
                this.services.website_cookies.manageIframeSrc(
                    iframeEl,
                    generateGMapLink(dataset),
                );
            }
        }
    }
}

registry.category("public.interactions").add("website.map", Map);
