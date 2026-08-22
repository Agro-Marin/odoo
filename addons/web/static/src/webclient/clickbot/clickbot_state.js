// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";

export const CLICKBOT_RUNNING_KEY = "running.clickbot";

export const clickbotSkippedMenus = registry.category("clickbot_skipped_menus");

clickbotSkippedMenus.addValidation((entry) => entry === true);

export const clickbotHomeMenuSelectors = registry.category(
    "clickbot_home_menu_selectors",
);

clickbotHomeMenuSelectors.addValidation((entry) => typeof entry === "string");

for (const menu of ["base.menu_theme_store", "base.menu_third_party"]) {
    clickbotSkippedMenus.add(menu, true);
}
