/** @odoo-module native */
import { session } from "@web/session";
import {
    getClosestLiEls,
    setUtmsHtmlDataset,
    unhideConditionalElements,
} from "@website/utils/misc";

document.addEventListener("DOMContentLoaded", () => {
    setUtmsHtmlDataset();
    const htmlEl = document.documentElement;
    const country = session.geoip_country_code;
    if (country) {
        htmlEl.dataset.country = country;
    }
    htmlEl.dataset.logged = !session.is_website_user;

    unhideConditionalElements();

    document
        .querySelectorAll(".o_mega_menu > section.o_snippet_desktop_invisible")
        .forEach((el) => el.closest("li").classList.add("hidden_mega_menu_li"));

    const mobileInvisibleMegaMenuLiEls = getClosestLiEls(
        ".o_mega_menu > section.o_snippet_mobile_invisible",
    );
    if (!mobileInvisibleMegaMenuLiEls.length) {
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
});
