/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("website.utils.images");

/**
 * @param {HTMLElement} element
 */
export function onceAllImagesLoaded(element) {
    const imgEls =
        element.nodeName === "IMG" ? [element] : [...element.querySelectorAll("img")];
    log.pipeline("onceAllImagesLoaded", () => ({
        root: element.nodeName,
        images: imgEls.length,
        pending: imgEls.filter((imgEl) => !imgEl.complete).length,
    }));
    const defs = imgEls.map((imgEl) => {
        if (imgEl.complete) {
            return;
        }
        return new Promise((resolve, reject) => {
            imgEl.addEventListener("load", resolve, { once: true });
            imgEl.addEventListener("error", reject, { once: true });
        });
    });
    return Promise.all(defs);
}
