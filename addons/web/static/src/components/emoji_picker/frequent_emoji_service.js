// @ts-check
/** @odoo-module native */

import { reactive } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import {
    isPlainObject,
    readJSONStorage,
    writeJSONStorage,
} from "@web/core/browser/storage_json";
import { registry } from "@web/core/registry";

const STORAGE_KEY = "web.emoji.frequent";
const MAX_TRACKED = 200;

/**
 * Usage counts per emoji, shared across tabs through the `storage` event.
 *
 * `revision` is what consumers watch: the counts live in a plain object, so a
 * component that wants to re-derive on any change has nothing else to key on.
 */
class FrequentEmojiService {
    /** @type {Record<string, number>} */
    all;
    revision = 0;
    /** @type {((ev: StorageEvent) => void) | undefined} */
    onStorage;

    constructor() {
        this.all = FrequentEmojiService.read();
    }

    /**
     * Subscribe to other tabs. Called on the reactive proxy rather than from the
     * constructor on purpose: an arrow bound in the constructor captures the raw
     * instance, and writes through it notify nobody.
     */
    listen() {
        this.onStorage = (/** @type {StorageEvent} */ ev) => this.applyStorage(ev);
        browser.addEventListener("storage", this.onStorage);
    }

    /**
     * @param {StorageEvent} ev
     */
    applyStorage(ev) {
        if (ev.key !== STORAGE_KEY && ev.key !== null) {
            return;
        }
        // A null key is the whole store being cleared.
        this.all = ev.key === null ? {} : FrequentEmojiService.read(ev.newValue);
        this.revision++;
    }

    /**
     * @param {string | null} [raw] the `storage` event's payload, if this is a
     *  cross-tab update rather than the initial read
     * @returns {Record<string, number>}
     */
    static read(raw) {
        if (raw === undefined) {
            return readJSONStorage(STORAGE_KEY, {
                fallback: /** @type {Record<string, number>} */ ({}),
                validate: isPlainObject,
            });
        }
        try {
            const value = JSON.parse(raw || "{}");
            return isPlainObject(value) ? value : {};
        } catch {
            return {};
        }
    }

    /**
     * @param {string} codepoints
     */
    incrementEmojiUsage(codepoints) {
        const isNew = !(codepoints in this.all);
        this.all[codepoints] ??= 0;
        this.all[codepoints]++;
        if (isNew) {
            this.forgetColdest(codepoints);
        }
        this.revision++;
        writeJSONStorage(STORAGE_KEY, this.all);
    }

    /**
     * Tracking is unbounded otherwise: every emoji ever used keeps a counter.
     * @param {string} keep the emoji just used, which is never a candidate
     */
    forgetColdest(keep) {
        const tracked = Object.keys(this.all);
        const excess = tracked.length - MAX_TRACKED;
        if (excess <= 0) {
            return;
        }
        const coldest = tracked
            .filter((codepoints) => codepoints !== keep)
            .sort((a, b) => this.all[a] - this.all[b]);
        for (const cold of coldest.slice(0, excess)) {
            delete this.all[cold];
        }
    }

    /**
     * @param {number} [limit]
     * @returns {string[]}
     */
    getMostFrequent(limit) {
        return Object.entries(this.all)
            .sort(([, usageA], [, usageB]) => usageB - usageA)
            .slice(0, limit ?? Infinity)
            .map(([codepoints]) => codepoints);
    }

    destroy() {
        if (this.onStorage) {
            browser.removeEventListener("storage", this.onStorage);
            this.onStorage = undefined;
        }
    }
}

export const frequentEmojiService = {
    start() {
        const service = reactive(new FrequentEmojiService());
        service.listen();
        return service;
    },
};

registry.category("services").add("web.frequent.emoji", frequentEmojiService);
