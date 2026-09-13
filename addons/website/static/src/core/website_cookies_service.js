/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { registry } from "@web/core/registry";
import { EventBus } from "@website/utils/misc";

const log = makeLogger("website.service.cookies");

export const websiteCookiesService = {
    dependencies: ["public.interactions"],
    start(env, deps) {
        const bus = new EventBus();
        const publicInteractions = deps["public.interactions"];
        log.lifecycle("start");
        /**
         * @param {HTMLIFrameElement} iframeEl
         * @param {string} src
         */
        function manageIframeSrc(iframeEl, src) {
            if (!iframeEl.closest("[data-need-cookies-approval]")) {
                log.logic("manageIframeSrc: no approval needed, set src", () => ({
                    src,
                }));
                iframeEl.setAttribute("src", src);
            } else {
                log.logic(
                    "manageIframeSrc: cookies approval needed, blank src",
                    () => ({
                        src,
                    }),
                );
                iframeEl.dataset.nocookieSrc = src;
                iframeEl.setAttribute("src", "about:blank");
                iframeEl.dataset.needCookiesApproval = "true";
                publicInteractions.startInteractions(iframeEl);
            }
        }

        return { bus, manageIframeSrc };
    },
};

registry.category("services").add("website_cookies", websiteCookiesService);
