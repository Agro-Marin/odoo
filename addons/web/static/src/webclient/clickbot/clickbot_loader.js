// @ts-check
/** @odoo-module native */

/** @module @web/webclient/clickbot/clickbot_loader - Debug menu item that loads and runs the click-everywhere automated test bot */

/**
 * @param {string} [xmlId]
 * @param {boolean} [light]
 * @param {any} [currentState]
 */
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
export async function startClickEverywhere(xmlId, light, currentState) {
    await loadBundle("web.assets_clickbot");
    /** @type {any} */ (window).clickEverywhere(xmlId, light, currentState);
}

export function runClickTestItem({ env }) {
    return {
        type: "item",
        description: _t("Run Click Everywhere"),
        callback: () => {
            startClickEverywhere();
        },
        sequence: 460,
        section: "testing",
    };
}

// localStorage.getItem returns null for missing keys, but the stored value can
// also be malformed (a garbage string, or a test patch returning undefined),
// which makes JSON.parse throw at module-evaluation time and would blank the
// whole bundle. Guard with try/catch (same pattern as menu_service / user.js).
const rawClickbotState = browser.localStorage.getItem("running.clickbot");
let currentState = null;
if (rawClickbotState) {
    try {
        currentState = JSON.parse(rawClickbotState);
    } catch {
        currentState = null;
    }
}
if (currentState) {
    // Fire-and-forget: `.catch` so a failed bundle load (loadBundle rejecting)
    // surfaces as a log rather than an unhandled rejection at module load.
    startClickEverywhere(currentState.xmlId, currentState.light, currentState).catch(
        (error) => console.error("[clickbot] failed to auto-start:", error),
    );
}

export default {
    startClickEverywhere,
    runClickTestItem,
};

registry
    .category("debug")
    .category("default")
    .add("runClickTestItem", /** @type {any} */ (runClickTestItem));
