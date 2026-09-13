/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { jsToPyLocale } from "@web/core/l10n/utils";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

const log = makeLogger("website.service.page");

export const websitePageService = {
    start() {
        const htmlEl = document.querySelector("html");
        const match = htmlEl.dataset.mainObject?.match(/(.+)\((-?\d+),(.*)\)/);
        log.lifecycle("start", () => ({
            websiteId: htmlEl.dataset.websiteId,
            lang: htmlEl.getAttribute("lang"),
            mainObject: htmlEl.dataset.mainObject,
            parsed: !!match,
        }));

        return {
            context: {
                ...user.context,
                website_id: htmlEl.dataset.websiteId | 0,
                lang: jsToPyLocale(htmlEl.getAttribute("lang")) || "en_US",
                user_lang: user.context.lang,
            },
            mainObject: {
                model: match && match[1],
                id: match && match[2] | 0,
            },
        };
    },
};

registry.category("services").add("website_page", websitePageService);
