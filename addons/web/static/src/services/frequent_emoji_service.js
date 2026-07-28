// @ts-check
/** @odoo-module native */

/** @module @web/services/frequent_emoji_service - Tracks and retrieves frequently used emojis from localStorage */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isPlainObject,
    readJSONStorage,
    writeJSONStorage,
} from "@web/core/browser/storage_json";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "web.emoji.frequent";
/** Cap on tracked emojis; the picker shows 42 of them. @see incrementEmojiUsage */
const MAX_TRACKED = 200;
/**
 * @typedef {Object} FrequentEmojiState
 * @property {Record<string, number>} all - map of codepoints to usage counts
 * @property {(codepoints: string) => void} incrementEmojiUsage
 * @property {(limit?: number) => string[]} getMostFrequent
 * @property {() => void} destroy - detaches the cross-tab `storage` listener;
 *   part of the service contract, called by `env.destroy()` on teardown
 */

/**
 * Parse a ``storage`` event's raw ``newValue``, which arrives as a string and
 * so cannot go through {@link readJSONStorage}. Same shape contract: anything
 * that is not a plain object degrades to ``{}``, because a ``null`` or scalar
 * reaches ``Object.entries`` on every render via ``computeRecentEmojis`` and
 * permanently bricks the emoji picker.
 * @param {string | null} raw
 * @returns {Record<string, number>}
 */
function parseFrequent(raw) {
    try {
        const value = JSON.parse(raw || "{}");
        return isPlainObject(value) ? value : {};
    } catch {
        return {};
    }
}

export const frequentEmojiService = {
    /** @returns {FrequentEmojiState} */
    start() {
        const state = reactive({
            /** @type {Record<string, number>} */
            all: readJSONStorage(STORAGE_KEY, {
                fallback: /** @type {Record<string, number>} */ ({}),
                validate: isPlainObject,
            }),
            /**
             * Increment usage count for the given emoji codepoints.
             * @param {string} codepoints - the emoji codepoints identifier
             */
            incrementEmojiUsage(codepoints) {
                // Unbounded, this grows one entry per distinct emoji ever used
                // (~1.5k) and is re-read and re-sorted on every render of the
                // picker, to display 42 of them. Keep a generous multiple of
                // what is displayed and drop the coldest tail.
                const isNew = !(codepoints in state.all);
                state.all[codepoints] ??= 0;
                state.all[codepoints]++;
                // Only an insertion can push the map over the cap, so the scan
                // stays off the hot path of re-using an emoji already tracked.
                if (isNew) {
                    const tracked = Object.keys(state.all);
                    const excess = tracked.length - MAX_TRACKED;
                    if (excess > 0) {
                        // The emoji just used is exempt: it enters with a count
                        // of 1, so it is by definition the coldest entry and
                        // would be evicted before it could ever earn its place
                        // -- leaving a full cache permanently unable to learn.
                        const coldest = tracked
                            .filter((tracking) => tracking !== codepoints)
                            .sort((a, b) => state.all[a] - state.all[b]);
                        for (const cold of coldest.slice(0, excess)) {
                            delete state.all[cold];
                        }
                    }
                }
                writeJSONStorage(STORAGE_KEY, state.all);
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
            /** Detach the cross-tab listener on env teardown. */
            destroy() {
                browser.removeEventListener("storage", onStorage);
            },
        });

        /** @type {(ev: StorageEvent) => void} */
        const onStorage = (ev) => {
            if (ev.key === STORAGE_KEY) {
                state.all = parseFrequent(ev.newValue);
            } else if (ev.key === null) {
                // `localStorage.clear()` in another tab.
                state.all = {};
            }
        };
        browser.addEventListener("storage", onStorage);

        return state;
    },
};

registry.category("services").add("web.frequent.emoji", frequentEmojiService);
