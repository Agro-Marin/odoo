// @ts-check
/** @odoo-module native */

/** @module @web/core/browser/anchor_scroll */

import { globalSingleton } from "@web/core/utils/global_singleton";

import { browser } from "./browser.js";

// Guarded like `router`'s listeners: a second evaluation of this module would
// otherwise install a second click handler on the same window.
const _anchorScroll = globalSingleton("anchorScroll", () => ({ started: false }));

if (!_anchorScroll.started) {
    _anchorScroll.started = true;
    browser.addEventListener("click", (ev) => {
        // See `router.js`'s own click handler: `ev.target` is not always an
        // Element, and this listener is on the window.
        const target = /** @type {Element} */ (ev.target);
        if (typeof target?.closest !== "function") {
            return;
        }
        if (target.closest("a")?.getAttribute("href") === "#") {
            ev.preventDefault();
        }
    });
}
