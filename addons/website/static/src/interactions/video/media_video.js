/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { Interaction } from "@web/public/interaction";
import { generateVideoIframe } from "@website/js/content/generate_video_iframe";
import { setupAutoplay, triggerAutoplay } from "@website/utils/videos";

const log = makeLogger("website.interaction.media_video");

export class MediaVideo extends Interaction {
    static selector = ".media_iframe_video";
    dynamicSelectors = {
        ...this.dynamicSelectors,
        _popup: () => this.el.closest(".s_popup"),
    };
    dynamicContent = {
        _popup: {
            "t-on-shown.bs.modal": () => {
                this.services.website_cookies.manageIframeSrc(
                    this.el.querySelector("iframe"),
                    this.el.dataset.oeExpression || this.el.dataset.src,
                );
            },
            "t-on-hide.bs.modal": () => {
                this.el.querySelector("iframe").src = "";
            },
        },
        _document: {
            "t-on-optionalCookiesAccepted": () => {
                this.cookiesAccepted = true;
            },
        },
        ":scope > .media_iframe_video_size": {
            "t-att-class": () => ({ "d-none": !this.cookiesAccepted }),
        },
    };

    setup() {
        this.cookiesAccepted = this.el.dataset.needCookiesApproval !== "true";
        log.lifecycle("MediaVideo setup", () => ({
            cookiesAccepted: this.cookiesAccepted,
        }));
    }

    start() {
        let iframeEl = this.el.querySelector(":scope > iframe");

        if (!iframeEl) {
            iframeEl = generateVideoIframe(
                this.el,
                this.services.website_cookies.manageIframeSrc,
            );
            log.logic("MediaVideo start: generated iframe", () => ({
                generated: !!iframeEl,
                src: this.el.dataset.oeExpression || this.el.dataset.src,
            }));
        }

        if (iframeEl && !iframeEl.getAttribute("aria-label")) {
            iframeEl.setAttribute("aria-label", _t("Media video"));
        }

        if (iframeEl?.hasAttribute("src")) {
            const promise = setupAutoplay(
                iframeEl.getAttribute("src"),
                !!this.el.dataset.needCookiesApproval,
            );
            log.logic("MediaVideo start: autoplay setup", () => ({
                hasPromise: !!promise,
                needCookiesApproval: !!this.el.dataset.needCookiesApproval,
            }));
            if (promise) {
                this.waitFor(promise).then(
                    this.bindDeferred(() => triggerAutoplay(iframeEl)),
                );
            }
        }
    }
}

registry.category("public.interactions").add("website.media_video", MediaVideo);
