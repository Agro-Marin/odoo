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

// ``getItem`` returns ``null`` for missing keys in real localStorage,
// which ``JSON.parse(null)`` accepts and resolves to ``null``. But
// test patches occasionally return ``undefined`` (HOOT's
// ``patchWithCleanup`` with an incomplete getter), which makes
// ``JSON.parse(undefined)`` throw ``SyntaxError: "undefined" is not
// valid JSON``. Guard with an explicit fall-back so module load
// stays safe across both shapes.
const rawClickbotState = browser.localStorage.getItem("running.clickbot");
const currentState = rawClickbotState ? JSON.parse(rawClickbotState) : null;
if (currentState) {
    startClickEverywhere(currentState.xmlId, currentState.light, currentState);
}

export default {
    startClickEverywhere,
    runClickTestItem,
};

registry
    .category("debug")
    .category("default")
    .add("runClickTestItem", /** @type {any} */ (runClickTestItem));
