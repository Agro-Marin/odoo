/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";
import { MEDIAS_BREAKPOINTS, SIZES } from "@web/ui/viewport";

const log = makeLogger("website.interaction.cookies_approval");

export class CookiesApproval extends Interaction {
    static selector = "[data-need-cookies-approval]";
    dynamicContent = {
        _document: {
            "t-on-optionalCookiesAccepted.once": this.onOptionalCookiesAccepted,
        },
    };

    setup() {
        this.iframeEl =
            this.el.tagName === "IFRAME" ? this.el : this.el.querySelector("iframe");
        log.lifecycle("CookiesApproval setup", () => ({
            tagName: this.el.tagName,
            hasIframe: !!this.iframeEl,
        }));
    }

    start() {
        log.logic("CookiesApproval start: warning decision", () => ({
            hasIframe: !!this.iframeEl,
            hasWarning:
                !!this.iframeEl?.nextElementSibling?.classList.contains(
                    "o_no_optional_cookie",
                ),
        }));
        if (this.iframeEl && !this.getCookiesWarningEl()) {
            this.addOptionalCookiesWarning();
        }
    }

    getCookiesWarningEl() {
        if (
            this.iframeEl.nextElementSibling?.classList.contains("o_no_optional_cookie")
        ) {
            return this.iframeEl.nextElementSibling;
        }
        return null;
    }

    addOptionalCookiesWarning() {
        const endRender = log.perf("CookiesApproval render warning");
        this.renderAt(
            "website.cookiesWarning",
            {
                extraStyle: this.iframeEl.parentElement.classList.contains(
                    "media_iframe_video",
                )
                    ? `aspect-ratio: 16/9; max-width: ${MEDIAS_BREAKPOINTS[SIZES.SM].maxWidth}px;`
                    : "",
                extraClasses:
                    getComputedStyle(this.iframeEl.parentElement).position ===
                    "absolute"
                        ? ""
                        : "my-3",
            },
            this.iframeEl,
            "afterend",
        );
        endRender();
    }

    onOptionalCookiesAccepted() {
        delete this.el.dataset.needCookiesApproval;
        if (this.iframeEl?.dataset.nocookieSrc) {
            log.logic("CookiesApproval accepted: restore iframe src", () => ({
                src: this.iframeEl.dataset.nocookieSrc,
            }));
            this.iframeEl.src = this.iframeEl.dataset.nocookieSrc;
            delete this.iframeEl.dataset.nocookieSrc;
        }
    }
}

registry
    .category("public.interactions")
    .add("website.cookies_approval", CookiesApproval);
