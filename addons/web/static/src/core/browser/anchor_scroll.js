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
        const href = /** @type {Element} */ (ev.target)
            .closest("a")
            ?.getAttribute("href");
        if (href === "#") {
            ev.preventDefault();
        }
    });
}
