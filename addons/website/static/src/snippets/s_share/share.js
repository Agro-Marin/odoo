/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { Interaction } from "@web/public/interaction";

const log = makeLogger("website.snippet.s_share");

export class Share extends Interaction {
    static selector = ".s_share, .oe_share";
    dynamicContent = {
        a: { "t-on-click": this.onClick },
    };

    /**
     * @param {Event} ev
     */
    onClick(ev) {
        const urlParams = ["u", "url", "body"];
        const titleParams = ["title", "text", "subject", "description"];
        const mediaParams = ["media"];
        const aEl = ev.currentTarget;

        const modifiedUrl = new URL(aEl.href);

        if (
            ![...urlParams, ...titleParams, ...mediaParams].some((param) =>
                modifiedUrl.searchParams.has(param),
            )
        ) {
            log.logic("onClick: no share params, default navigation", () => ({
                href: aEl.href,
            }));
            return;
        }

        ev.preventDefault();
        ev.stopPropagation();

        const currentUrl = window.location.href;

        const urlParamFound = urlParams.find((param) =>
            modifiedUrl.searchParams.has(param),
        );
        if (urlParamFound) {
            modifiedUrl.searchParams.set(urlParamFound, currentUrl);
        }

        const titleParamFound = titleParams.find((param) =>
            modifiedUrl.searchParams.has(param),
        );
        if (titleParamFound) {
            const currentTitle = document.title;
            if (aEl.classList.contains("s_share_whatsapp")) {
                modifiedUrl.searchParams.set(
                    titleParamFound,
                    `${currentTitle} ${currentUrl}`,
                );
            } else {
                modifiedUrl.search = modifiedUrl.search.replace(
                    encodeURIComponent("{title}"),
                    encodeURIComponent(currentTitle),
                );
            }
        }

        const mediaParamFound = mediaParams.find((param) =>
            modifiedUrl.searchParams.has(param),
        );
        if (mediaParamFound) {
            const ogImageEl = document.querySelector("meta[property='og:image']");
            if (ogImageEl) {
                const media = ogImageEl.content;
                modifiedUrl.searchParams.set(mediaParamFound, media);
            } else {
                modifiedUrl.searchParams.delete(mediaParamFound);
            }
        }

        log.logic("onClick: opening share popup", () => ({
            urlParam: urlParamFound,
            titleParam: titleParamFound,
            mediaParam: mediaParamFound,
            whatsapp: aEl.classList.contains("s_share_whatsapp"),
            hasOgImage: !!document.querySelector("meta[property='og:image']"),
        }));
        window.open(
            modifiedUrl.toString(),
            aEl.target,
            "menubar=no,toolbar=no,resizable=yes,scrollbars=yes,height=550,width=600",
        );
    }
}

registry.category("public.interactions").add("website.share", Share);
