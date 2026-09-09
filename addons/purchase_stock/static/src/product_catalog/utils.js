/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

export const SUGGEST_TOGGLE_STORAGE_KEY = "purchase_stock.suggest_toggle_state";
const off = () => ({ isOn: false });

export function getSuggestToggleState(poState) {
    if (poState !== "draft") {
        return off();
    }
    try {
        return (
            JSON.parse(browser.localStorage.getItem(SUGGEST_TOGGLE_STORAGE_KEY)) ??
            off()
        );
    } catch {
        return off();
    }
}
