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

class FrequentEmojiService {
    /** @type {Record<string, number>} */
    all;
    revision = 0;
    /** @type {((ev: StorageEvent) => void) | undefined} */
    onStorage;

    constructor() {
        this.all = FrequentEmojiService.read();
    }

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
        this.all = ev.key === null ? {} : FrequentEmojiService.read(ev.newValue);
        this.revision++;
    }

    /**
     * @param {string | null} [raw]
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
     * @param {string} keep
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
