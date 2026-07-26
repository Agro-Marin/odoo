/** @odoo-module native */
import { router } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";

/*
This prevents the router from trying to extract an action from the url if it starts with /odoo/documents
 */
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
                // getAttribute returns the raw attribute, which is typically a
                // relative path for internal links: resolve it against the
                // current origin so `new URL` does not throw on those.
                url = new URL(href, browser.location.origin);
            } catch {
                return;
            }
            if (
                browser.location.host === url.host &&
                browser.location.pathname.startsWith("/odoo") &&
                url.pathname.startsWith("/odoo/documents/") &&
                // read `target` off the anchor, not off the (possibly nested
                // <span>/<i>) node that was actually clicked
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

/* if you guys at framework-js read this, we are sorry, bigram-request */
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
