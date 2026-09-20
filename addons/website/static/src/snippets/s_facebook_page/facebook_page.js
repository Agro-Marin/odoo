/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { clamp } from "@web/core/utils/format/numbers";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.snippet.s_facebook_page");

export class FacebookPage extends Interaction {
    static selector = ".o_facebook_page";

    setup() {
        this.previousWidth = 0;
        const params = pick(
            this.el.dataset,
            "href",
            "id",
            "height",
            "tabs",
            "small_header",
            "hide_cover",
        );
        if (!params.href) {
            log.logic("setup: no href, nothing to render");
            return;
        }
        if (params.id) {
            params.href = `https://www.facebook.com/${params.id}`;
            delete params.id;
        }

        this.renderIframe(params);

        this.resizeObserver = new ResizeObserver(
            this.debounced(this.renderIframe.bind(this, params), 100),
        );
        this.resizeObserver.observe(this.el.parentElement);
        log.lifecycle("setup: resize observer attached", () => ({
            href: params.href,
        }));
        this.registerCleanup(() => {
            this.resizeObserver.disconnect();
            log.lifecycle("cleanup: resize observer disconnected");
            this.el.replaceChildren();
        });
    }

    /**
     * @param {Object} params
     */
    renderIframe(params) {
        params.width = clamp(
            Math.floor(this.el.getBoundingClientRect().width),
            180,
            500,
        );
        if (this.previousWidth !== params.width) {
            log.logic("renderIframe: width changed, rebuilding iframe", () => ({
                previous: this.previousWidth,
                width: params.width,
            }));
            this.previousWidth = params.width;
            const searchParams = new URLSearchParams(params);

            const iframeEl = document.createElement("iframe");
            iframeEl.setAttribute("style", "border: none; overflow: hidden;");
            iframeEl.setAttribute("aria-label", _t("Facebook"));
            iframeEl.height = params.height;
            iframeEl.width = params.width;

            this.el.replaceChildren(iframeEl);

            const src = "https://www.facebook.com/plugins/page.php?" + searchParams;
            this.services.website_cookies.manageIframeSrc(iframeEl, src);
        }
    }
}

registry.category("public.interactions").add("website.facebook_page", FacebookPage);
