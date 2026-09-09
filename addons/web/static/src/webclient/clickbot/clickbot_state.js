// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

export const CLICKBOT_RUNNING_KEY = "running.clickbot";

/** @returns {string | null} */
export function readClickbotRun() {
    try {
        return browser.localStorage.getItem(CLICKBOT_RUNNING_KEY);
    } catch {
        return null;
    }
}

/** @param {string | null} value */
export function writeClickbotRun(value) {
    try {
        if (value === null) {
            browser.localStorage.removeItem(CLICKBOT_RUNNING_KEY);
        } else {
            browser.localStorage.setItem(CLICKBOT_RUNNING_KEY, value);
        }
    } catch {}
}

export const clickbotSkippedMenus = registry.category("clickbot_skipped_menus");

clickbotSkippedMenus.addValidation((entry) => entry === true);

export const clickbotHomeMenuSelectors = registry.category(
    "clickbot_home_menu_selectors",
);

clickbotHomeMenuSelectors.addValidation((entry) => typeof entry === "string");

for (const menu of ["base.menu_theme_store", "base.menu_third_party"]) {
    clickbotSkippedMenus.add(menu, true);
}
