// @ts-check
/** @odoo-module native */

/** @module @web/webclient/clickbot/clickbot_loader */

/**
 * @param {string} [xmlId]
 * @param {boolean} [light]
 * @param {any} [currentState]
 */
import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
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
