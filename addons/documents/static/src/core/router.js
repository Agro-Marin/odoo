/** @odoo-module native */
import { router } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";

browser.addEventListener(
    "click",
    (ev) => {
        if (ev.defaultPrevented || ev.target.closest("[contenteditable]")) {
            return;
        }
        const anchor = ev.target.closest("a");
        const href = anchor?.getAttribute("href");
        if (href && !href.startsWith("#")) {
            let url;
            try {
                url = new URL(href, browser.location.origin);
            } catch {
                return;
            }
            if (
                browser.location.host === url.host &&
                browser.location.pathname.startsWith("/odoo") &&
                url.pathname.startsWith("/odoo/documents/") &&
                anchor.target !== "_blank"
            ) {
                ev.stopPropagation();
            }
        }
    },
    {
        capture: true,
    }
);

patch(router, {
    stateToUrl(state) {
        const url = super.stateToUrl(state);
        if (url.startsWith("/odoo/documents") && state.access_token) {
            return (
                `/odoo/documents/${encodeURIComponent(state.access_token)}` +
                (Object.hasOwn(state, "debug") ? `?debug=${state.debug}` : "")
            );
        }
        return url;
    },
});
