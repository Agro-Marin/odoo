/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

export class FooterSlideout extends Interaction {
    static selector = "#wrapwrap";
    static selectorHas = ".o_footer_slideout";

    start() {
        if (/^((?!chrome|android).)*safari/i.test(navigator.userAgent)) {
            const pixelEl = document.createElement("div");
            pixelEl.style.width = "1px";
            pixelEl.style.height = "1px";
            pixelEl.style.marginTop = "-1px";
            pixelEl.style.backgroundColor = "transparent";
            pixelEl.style.backgroundAttachment = "fixed";
            pixelEl.style.backgroundImage =
                "url(/website/static/src/img/website_logo.svg)";
            this.insert(pixelEl);
        }
    }
}

registry.category("public.interactions").add("website.footer_slideout", FooterSlideout);

registry.category("public.interactions.edit").add("website.footer_slideout", {
    Interaction: FooterSlideout,
});
