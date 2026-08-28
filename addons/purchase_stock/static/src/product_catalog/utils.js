/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

export const SUGGEST_TOGGLE_STORAGE_KEY = "purchase_stock.suggest_toggle_state";
const off = () => ({ isOn: false });

/** False if PO is not draft, otherwise loads last toggle state from local storage (defaults to false)  */
export function getSuggestToggleState(poState) {
    if (poState !== "draft") {
        return off();
    }
    // Through `browser` so HOOT can mock it, and guarded because a corrupt or
    // hand-edited value would otherwise throw and take the catalog down with it.
    try {
        return (
            JSON.parse(browser.localStorage.getItem(SUGGEST_TOGGLE_STORAGE_KEY)) ??
            off()
        );
    } catch {
        return off();
    }
}
