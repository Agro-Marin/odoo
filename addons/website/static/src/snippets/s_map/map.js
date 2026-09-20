/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { generateGMapIframe, generateGMapLink } from "@website/js/utils";

const log = makeLogger("website.snippet.s_map");

export class Map extends Interaction {
    static selector = ".s_map";

    start() {
        log.logic("start", () => ({
            alreadyEmbedded: !!this.el.querySelector(".s_map_embedded"),
            hasAddress: !!this.el.dataset.mapAddress,
        }));
        if (!this.el.querySelector(".s_map_embedded")) {
            const dataset = this.el.dataset;
            if (dataset.mapAddress) {
                const iframeEl = generateGMapIframe();
                this.el.querySelector(".s_map_color_filter").before(iframeEl);
                this.services.website_cookies.manageIframeSrc(
                    iframeEl,
                    generateGMapLink(dataset),
                );
                log.lifecycle("iframe inserted, src handed to cookie consent");
            }
        }
    }
}

registry.category("public.interactions").add("website.map", Map);
