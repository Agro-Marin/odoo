// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/anchor_scroll - Prevents default scroll on bare "#" anchor clicks */

import { browser } from "./browser.js";

browser.addEventListener("click", (ev) => {
    const href = /** @type {Element} */ (ev.target).closest("a")?.getAttribute("href");
    if (href && href === "#") {
        ev.preventDefault(); // a lone "#" href only activates the anchor tag
        return;
    }
});
