// @ts-check
/** @odoo-module native */

import { globalSingleton } from "@web/core/utils/global_singleton";

import { browser } from "./browser.js";

const _anchorScroll = globalSingleton("anchorScroll", () => ({ started: false }));

if (!_anchorScroll.started) {
    _anchorScroll.started = true;
    browser.addEventListener("click", (ev) => {
        const target = /** @type {Element} */ (ev.target);
        if (typeof target?.closest !== "function") {
            return;
        }
        if (target.closest("a")?.getAttribute("href") === "#") {
            ev.preventDefault();
        }
    });
}
