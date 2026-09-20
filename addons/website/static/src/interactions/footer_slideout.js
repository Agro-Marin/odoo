/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.footer_slideout");

export class FooterSlideout extends Interaction {
    static selector = "#wrapwrap";
    static selectorHas = ".o_footer_slideout";

    start() {
        if (/^((?!chrome|android).)*safari/i.test(navigator.userAgent)) {
            log.logic(
                "FooterSlideout start: safari, insert fixed-background pixel",
                () => ({
                    userAgent: navigator.userAgent,
                }),
            );
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
