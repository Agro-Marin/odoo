// @ts-check
/** @odoo-module native */

/** @module @web/components/emoji_picker/frequent_emoji_service */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isPlainObject,
    readJSONStorage,
    writeJSONStorage,
} from "@web/core/browser/storage_json";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "web.emoji.frequent";
/** @see incrementEmojiUsage */
const MAX_TRACKED = 200;
/**
 * @typedef {Object} FrequentEmojiState
 * @property {Record<string, number>} all
 * @property {(codepoints: string) => void} incrementEmojiUsage
 * @property {(limit?: number) => string[]} getMostFrequent
 * @property {() => void} destroy
 */

/**
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
             * @param {string} codepoints
             */
            incrementEmojiUsage(codepoints) {
                const isNew = !(codepoints in state.all);
                state.all[codepoints] ??= 0;
                state.all[codepoints]++;
                if (isNew) {
                    const tracked = Object.keys(state.all);
                    const excess = tracked.length - MAX_TRACKED;
                    if (excess > 0) {
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
             * @param {number} [limit]
             * @returns {string[]}
             */
            getMostFrequent(limit) {
                return Object.entries(state.all)
                    .sort(([, usage_1], [, usage_2]) => usage_2 - usage_1)
                    .slice(0, limit ?? Infinity)
                    .map(([codepoints]) => codepoints);
            },
            destroy() {
                browser.removeEventListener("storage", onStorage);
            },
        });

        /** @type {(ev: StorageEvent) => void} */
        const onStorage = (ev) => {
            if (ev.key === STORAGE_KEY) {
                state.all = parseFrequent(ev.newValue);
            } else if (ev.key === null) {
                state.all = {};
            }
        };
        browser.addEventListener("storage", onStorage);

        return state;
    },
};

registry.category("services").add("web.frequent.emoji", frequentEmojiService);
