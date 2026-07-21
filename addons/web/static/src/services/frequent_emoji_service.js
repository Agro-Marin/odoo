// @ts-check
/** @odoo-module native */

/** @module @web/services/frequent_emoji_service - Tracks and retrieves frequently used emojis from localStorage */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
/**
 * @typedef {Object} FrequentEmojiState
 * @property {Record<string, number>} all - map of codepoints to usage counts
 * @property {(codepoints: string) => void} incrementEmojiUsage
 * @property {(limit?: number) => string[]} getMostFrequent
 */

/**
 * Parse the stored frequent-emoji map defensively. ``JSON.parse("null")``
 * returns ``null`` (which passes a bare try/catch), and any non-object value
 * then throws in ``Object.entries`` on every render via ``computeRecentEmojis``
 * — permanently bricking the emoji picker until localStorage is cleared by
 * hand. Accept ONLY a plain object; anything else degrades to ``{}``.
 * @param {string | null} raw
 * @returns {Record<string, number>}
 */
function parseFrequent(raw) {
    try {
        const value = JSON.parse(raw || "{}");
        return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    } catch {
        return {};
    }
}

export const frequentEmojiService = {
    /** @returns {FrequentEmojiState} */
    start() {
        const state = reactive({
            /** @type {Record<string, number>} */
            all: parseFrequent(browser.localStorage.getItem("web.emoji.frequent")),
            /**
             * Increment usage count for the given emoji codepoints.
             * @param {string} codepoints - the emoji codepoints identifier
             */
            incrementEmojiUsage(codepoints) {
                state.all[codepoints] ??= 0;
                state.all[codepoints]++;
                try {
                    browser.localStorage.setItem(
                        "web.emoji.frequent",
                        JSON.stringify(state.all),
                    );
                } catch {
                    // localStorage unavailable/full: usage tracking isn't
                    // persisted; picking the emoji must still work.
                }
            },
            /**
             * Return the most frequently used emoji codepoints, sorted by usage.
             * @param {number} [limit] - max number of results (defaults to all)
             * @returns {string[]} codepoints sorted by descending usage
             */
            getMostFrequent(limit) {
                return Object.entries(state.all)
                    .sort(([, usage_1], [, usage_2]) => usage_2 - usage_1)
                    .slice(0, limit ?? Infinity)
                    .map(([codepoints]) => codepoints);
            },
        });
        const onStorage = (ev) => {
            if (ev.key === "web.emoji.frequent") {
                state.all = parseFrequent(ev.newValue);
            } else if (ev.key === null) {
                // Whole storage cleared (e.g. logout).
                state.all = {};
            }
        };
        browser.addEventListener("storage", onStorage);
        // Remove the window listener on env teardown — without this each env
        // (every JS test mount, every embedded/public context) leaks a
        // ``storage`` handler pinning this reactive state forever, and every
        // storage event fans out to all of them. Mirrors the destroy() the
        // sibling window-listener services (name, slow_rpc, tooltip) added.
        state.destroy = () => browser.removeEventListener("storage", onStorage);
        return state;
    },
};

registry.category("services").add("web.frequent.emoji", frequentEmojiService);
