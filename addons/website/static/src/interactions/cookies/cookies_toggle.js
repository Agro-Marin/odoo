/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";
import { onceAllImagesLoaded } from "@website/utils/images";

const log = makeLogger("website.interaction.cookies_toggle");

export class CookiesToggle extends Interaction {
    static selector = ".o_cookies_bar_toggle";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _cookiesbus: () => this.services.website_cookies.bus,
    };
    dynamicContent = {
        _root: { "t-on-click": this.onClick },
        _cookiesbus: { "t-on-cookiesBar.discard": this.onClick },
        ".o_cookies_bar_toggle_label": { "t-out": this.toggleText },
        ".fa": {
            "t-att-class": () => ({
                "fa-eye": !this.isModalShown(),
                "fa-eye-slash": this.isModalShown(),
            }),
        },
    };

    setup() {
        this.cookiesModalEl = this.el.nextElementSibling.querySelector(".modal");
        log.lifecycle("CookiesToggle setup", () => ({
            hasModal: !!this.cookiesModalEl,
        }));
    }

    isModalShown() {
        return this.cookiesModalEl.classList.contains("show");
    }

    toggleText() {
        return this.isModalShown()
            ? _t("Hide the cookies bar")
            : _t("Show the cookies bar");
    }

    /**
     * @param {MouseEvent} ev
     */
    async onClick(ev) {
        if (ev.currentTarget === this.el) {
            this.services.website_cookies.bus.trigger("cookiesBar.toggle");
        }

        if (
            !this.isModalShown() ||
            !this.cookiesModalEl.classList.contains("s_popup_bottom")
        ) {
            log.logic("CookiesToggle onClick: reset inset", () => ({
                shown: this.isModalShown(),
                fromToggle: ev.currentTarget === this.el,
            }));
            this.el.style.removeProperty("--cookies-bar-toggle-inset-block-end");
        } else {
            const endImages = log.perf("CookiesToggle onClick: wait bar images");
            await this.waitFor(onceAllImagesLoaded(this.cookiesModalEl));
            endImages();
            const popupHeight =
                this.cookiesModalEl.querySelector(".modal-content").offsetHeight;
            const toggleMargin = 8;
            const bottom =
                document.body.offsetHeight >
                popupHeight + this.el.offsetHeight + toggleMargin
                    ? `calc(
                    ${
                        getComputedStyle(
                            this.cookiesModalEl.querySelector(".modal-dialog"),
                        ).paddingBottom
                    }
                    + ${popupHeight + toggleMargin}px
                )`
                    : "";
            log.logic("CookiesToggle onClick: bottom bar, set inset", () => ({
                popupHeight,
                bottom,
            }));
            this.el.style.setProperty("--cookies-bar-toggle-inset-block-end", bottom);
        }
    }
}

registry.category("public.interactions").add("website.cookies_toggle", CookiesToggle);
