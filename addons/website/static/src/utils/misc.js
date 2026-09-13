/** @odoo-module native */
import { cookie as cookieManager } from "@web/core/browser/cookie";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("website.utils.misc");

export class EventBus extends EventTarget {
    trigger(name, payload) {
        this.dispatchEvent(new CustomEvent(name, { detail: payload }));
    }
}

export function getClosestLiEls(selector) {
    return Array.from(document.querySelectorAll(selector), (el) => el.closest("li"));
}

export function unhideConditionalElements() {
    const endUnhide = log.perf("unhideConditionalElements");
    const styleEl = document.createElement("style");
    styleEl.id = "conditional_visibility";
    document.head.appendChild(styleEl);
    const conditionalEls = document.querySelectorAll('[data-visibility="conditional"]');

    const desktopMegaMenuLiEls = getClosestLiEls(
        "header#top nav:not(.o_header_mobile) .o_mega_menu_toggle",
    );
    const mobileMegaMenuLiEls = getClosestLiEls(
        "header#top nav.o_header_mobile .o_mega_menu_toggle",
    );
    for (const conditionalEl of conditionalEls) {
        if (conditionalEl.parentElement.classList.contains("o_mega_menu")) {
            const desktopMegaMenuLiEl = conditionalEl.closest("li");
            const index = desktopMegaMenuLiEls.indexOf(desktopMegaMenuLiEl);
            const mobileMegaMenuLiEl = mobileMegaMenuLiEls[index];

            const visibilityId = conditionalEl.dataset.visibilityId;
            desktopMegaMenuLiEl.dataset.visibilityId = visibilityId;
            mobileMegaMenuLiEl.dataset.visibilityId = visibilityId;
        }
        const selectors = conditionalEl.dataset.visibilitySelectors;
        styleEl.sheet.insertRule(`${selectors} { display: none !important; }`);
    }

    for (const conditionalEl of conditionalEls) {
        conditionalEl.classList.remove("o_conditional_hidden");
    }
    endUnhide(() => ({
        conditional: conditionalEls.length,
        megaMenus: desktopMegaMenuLiEls.length,
        rules: styleEl.sheet.cssRules.length,
    }));
}

export function setUtmsHtmlDataset() {
    const htmlEl = document.documentElement;
    const cookieNamesToDataNames = {
        utm_source: "utmSource",
        utm_medium: "utmMedium",
        utm_campaign: "utmCampaign",
    };
    for (const [name, dsName] of Object.entries(cookieNamesToDataNames)) {
        const cookie = cookieManager.get(`odoo_${name}`);
        if (cookie) {
            htmlEl.dataset[dsName] = cookie.replace(/(^["']|["']$)/g, "");
        }
    }
}

/**
 * @param {string} link
 * @returns {URL|""}
 */
export function verifyHttpsUrl(link) {
    if (!link) {
        return "";
    }
    let url;
    try {
        url = new URL(link, window.location.href);
    } catch {
        log.logic("verifyHttpsUrl: unparsable link", () => ({ link }));
        return "";
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
        log.logic("verifyHttpsUrl: rejected protocol", () => ({
            protocol: url.protocol,
        }));
        return "";
    }
    return url;
}
