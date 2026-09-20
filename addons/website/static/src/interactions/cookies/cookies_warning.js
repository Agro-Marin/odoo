/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.interaction.cookies_warning");

export class CookiesWarning extends Interaction {
    static selector = ".o_no_optional_cookie";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _iframe: () => (this.keptIframeEl ??= this.el.previousElementSibling),
    };
    dynamicContent = {
        _root: {
            "t-on-click": () =>
                this.services.website_cookies.bus.trigger("cookiesBar.show"),
        },
        _iframe: {
            "t-att-class": () => ({
                "d-none": !!this.el.parentElement,
            }),
        },
        _document: {
            "t-on-optionalCookiesAccepted.once": () => this.el.remove(),
        },
    };
    setup() {
        log.lifecycle("CookiesWarning setup", () => ({
            previous: this.el.previousElementSibling?.tagName,
        }));
        this.keptIframeEl = undefined;
    }
}

registry.category("public.interactions").add("website.cookies_warning", CookiesWarning);
