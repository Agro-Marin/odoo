/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { session } from "@web/session";
import {
    getClosestLiEls,
    setUtmsHtmlDataset,
    unhideConditionalElements,
} from "@website/utils/misc";

const log = makeLogger("website.content.inject_dom");

document.addEventListener("DOMContentLoaded", () => {
    const endInject = log.perf("DOMContentLoaded inject");
    setUtmsHtmlDataset();
    const htmlEl = document.documentElement;
    const country = session.geoip_country_code;
    if (country) {
        htmlEl.dataset.country = country;
    }
    htmlEl.dataset.logged = !session.is_website_user;
    log.pipeline("html dataset set", () => ({
        country: country || null,
        logged: htmlEl.dataset.logged,
        utmSource: htmlEl.dataset.utmSource || null,
    }));

    unhideConditionalElements();

    document
        .querySelectorAll(".o_mega_menu > section.o_snippet_desktop_invisible")
        .forEach((el) => el.closest("li").classList.add("hidden_mega_menu_li"));

    const mobileInvisibleMegaMenuLiEls = getClosestLiEls(
        ".o_mega_menu > section.o_snippet_mobile_invisible",
    );
    if (!mobileInvisibleMegaMenuLiEls.length) {
        endInject(() => ({ mobileInvisibleMegaMenus: 0 }));
        return;
    }

    const desktopMegaMenuLiEls = getClosestLiEls(
        "header#top nav:not(.o_header_mobile) .o_mega_menu_toggle",
    );
    const mobileMegaMenuLiEls = getClosestLiEls(
        "header#top nav.o_header_mobile .o_mega_menu_toggle",
    );
    for (const mobileInvisibleMegaMenuLiEl of mobileInvisibleMegaMenuLiEls) {
        const index = desktopMegaMenuLiEls.indexOf(mobileInvisibleMegaMenuLiEl);
        mobileMegaMenuLiEls[index].classList.add("hidden_mega_menu_li");
    }
    endInject(() => ({
        mobileInvisibleMegaMenus: mobileInvisibleMegaMenuLiEls.length,
    }));
});
