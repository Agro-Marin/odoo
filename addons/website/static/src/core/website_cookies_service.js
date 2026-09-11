/** @odoo-module native */
import { registry } from "@web/core/registry";
import { EventBus } from "@website/utils/misc";

export const websiteCookiesService = {
    dependencies: ["public.interactions"],
    start(env, deps) {
        const bus = new EventBus();
        const publicInteractions = deps["public.interactions"];
        /**
         * @param {HTMLIFrameElement} iframeEl
         * @param {string} src
         */
        function manageIframeSrc(iframeEl, src) {
            if (!iframeEl.closest("[data-need-cookies-approval]")) {
                iframeEl.setAttribute("src", src);
            } else {
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
