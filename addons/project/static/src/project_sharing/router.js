/** @odoo-module native */
import { browser } from "@web/core/browser/browser";
import { router, startUrl } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";

patch(router, {
    /**
     * @param {{ [key: string]: any }} state
     * @returns {string}
     */
    stateToUrl(state) {
        const url = super.stateToUrl(state);
        return url.replace(startUrl(), "my/projects");
    },
    urlToState(urlObj) {
        const { pathname } = urlObj;
        urlObj.pathname = pathname.replace(
            /\/my\/projects\/([1234567890]+)\/project_sharing/,
            "/odoo/project.project/$1/project_sharing",
        );
        const state = super.urlToState(urlObj);
        if (state.actionStack?.length) {
            state.actionStack.shift();
        }
        return state;
    },
});

router.replaceState(router.urlToState(new URL(browser.location)));
