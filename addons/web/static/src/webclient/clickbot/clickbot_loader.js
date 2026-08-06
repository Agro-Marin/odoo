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

const RUNNING_KEY = "running.clickbot";
/**
 * A run older than this is a leftover from a crashed session, not one to
 * resume: silently launching a full clickbot run on an unrelated page load
 * days later is never what anyone wants.
 */
const RESUME_MAX_AGE_MS = 30 * 60 * 1000;

const rawClickbotState = browser.localStorage.getItem(RUNNING_KEY);
let currentState = null;
if (rawClickbotState) {
    try {
        currentState = JSON.parse(rawClickbotState);
    } catch {
        currentState = null;
    }
}
if (currentState) {
    const startedAt = currentState.startedAt;
    if (!Number.isFinite(startedAt) || Date.now() - startedAt > RESUME_MAX_AGE_MS) {
        browser.localStorage.removeItem(RUNNING_KEY);
        console.warn(
            "[clickbot] Found a stale saved run (older than 30 minutes); clearing it instead of auto-resuming.",
        );
    } else {
        startClickEverywhere(
            currentState.xmlId,
            currentState.light,
            currentState,
        ).catch((error) => console.error("[clickbot] failed to auto-start:", error));
    }
}

registry
    .category("debug")
    .category("default")
    .add("runClickTestItem", /** @type {any} */ (runClickTestItem));
