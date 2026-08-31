// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

export const CLICKBOT_RUNNING_KEY = "running.clickbot";

/**
 * Storage can be unavailable outright -- private mode, a policy that disables
 * it -- and then every access throws. `clickbot_loader.js` consults the saved
 * run at module scope in `web.assets_backend`, so an unguarded read there is a
 * throw during backend boot. Same shape as `action_storage.js`'s accessors.
 *
 * @returns {string | null}
 */
export function readClickbotRun() {
    try {
        return browser.localStorage.getItem(CLICKBOT_RUNNING_KEY);
    } catch {
        return null;
    }
}

/**
 * @param {string | null} value `null` clears the saved run
 */
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
