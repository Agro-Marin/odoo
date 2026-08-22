// @ts-check
/** @odoo-module native */

import { loadBundle } from "@web/core/assets";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";

import { CLICKBOT_RUNNING_KEY } from "./clickbot_state.js";

/**
 * @param {string} [xmlId]
 * @param {boolean} [light]
 * @param {any} [currentState]
 */
export async function startClickEverywhere(xmlId, light, currentState) {
    await loadBundle("web.assets_clickbot");
    /** @type {any} */ (window).clickEverywhere(xmlId, light, currentState);
}

function runClickTestItem() {
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

export const RESUME_MAX_AGE_MS = 30 * 60 * 1000;

/**
 * @param {string | null} raw
 * @param {number} now
 * @returns {{ verdict: "none" | "corrupt" | "stale" | "resume", state?: any }}
 */
export function decideClickbotResume(raw, now) {
    if (!raw) {
        return { verdict: "none" };
    }
    let state;
    try {
        state = JSON.parse(raw);
    } catch {
        return { verdict: "corrupt" };
    }
    if (!state || typeof state !== "object") {
        return { verdict: "corrupt" };
    }
    const { startedAt } = state;
    if (!Number.isFinite(startedAt) || now - startedAt > RESUME_MAX_AGE_MS) {
        return { verdict: "stale" };
    }
    return { verdict: "resume", state };
}

/**
 * @param {{ now?: number }} [options]
 * @returns {{ verdict: string, state?: any }}
 */
export function resumeClickbotRun({ now = Date.now() } = {}) {
    const outcome = decideClickbotResume(
        browser.localStorage.getItem(CLICKBOT_RUNNING_KEY),
        now,
    );
    if (outcome.verdict === "stale" || outcome.verdict === "corrupt") {
        browser.localStorage.removeItem(CLICKBOT_RUNNING_KEY);
        console.warn(
            `[clickbot] Discarding a ${outcome.verdict} saved run instead of auto-resuming.`,
        );
    } else if (outcome.verdict === "resume") {
        startClickEverywhere(
            outcome.state.xmlId,
            outcome.state.light,
            outcome.state,
        ).catch((error) => console.error("[clickbot] failed to auto-start:", error));
    }
    return outcome;
}

resumeClickbotRun();

registry
    .category("debug")
    .category("default")
    .add("runClickTestItem", /** @type {any} */ (runClickTestItem));
