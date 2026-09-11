/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";

export class InstagramPage extends Interaction {
    static selector = ".s_instagram_page";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _iframe: () => this.iframeEl,
    };
    dynamicContent = {
        _window: { "t-on-message": this.onMessage },
        _iframe: { "t-att-height": () => this.height },
    };

    setup() {
        this.iframeEl = document.createElement("iframe");
        this.iframeEl.setAttribute("scrolling", "no");
        this.iframeEl.setAttribute("aria-label", _t("Instagram"));
        this.iframeEl.classList.add("w-100");
        this.insert(this.iframeEl, this.el.querySelector(".o_instagram_container"));

        const iframeWidth = parseInt(getComputedStyle(this.iframeEl).width);
        this.height = Math.ceil(0.659 * iframeWidth + (iframeWidth < 432 ? 156 : 203));
    }

    start() {
        const src = `https://www.instagram.com/${this.el.dataset.instagramPage}/embed`;
        this.services.website_cookies.manageIframeSrc(this.iframeEl, src);
    }

    /**
     * @param {Event} ev
     */
    onMessage(ev) {
        if (
            ev.origin !== "https://www.instagram.com" ||
            this.iframeEl.contentWindow !== ev.source
        ) {
            return;
        }
        const evDataJSON = JSON.parse(ev.data);
        if (evDataJSON.type !== "MEASURE") {
            return;
        }
        const height = parseInt(evDataJSON.details.height);
        if (height) {
            this.height = height;
        }
    }
}

registry.category("public.interactions").add("website.instagram_page", InstagramPage);
