// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";

const KEY_PREFIX = "webclient_menu_usage";
const MAX_ENTRIES = 50;
const HALF_LIFE_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * @typedef {{ n: number, t: number }} UsageEntry count and last-use timestamp
 * @typedef {Record<string, UsageEntry>} UsageTable keyed by menu xmlid
 */

function storageKey() {
    return `${KEY_PREFIX}:${user.userId}`;
}

/** @returns {UsageTable} */
function read() {
    try {
        const raw = browser.localStorage.getItem(storageKey());
        const parsed = raw ? JSON.parse(raw) : null;
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
        return {};
    }
}

/** @param {UsageTable} table */
function write(table) {
    try {
        browser.localStorage.setItem(storageKey(), JSON.stringify(table));
    } catch {}
}

/**
 * @param {UsageEntry} entry
 * @param {number} now
 * @returns {number}
 */
function frecency(entry, now) {
    return entry.n * Math.pow(0.5, Math.max(0, now - entry.t) / HALF_LIFE_MS);
}

/**
 * What the user opens, and how recently: a per-user table in localStorage that
 * ranks the app grid's recents and the palette's empty query. A count halves
 * every week it goes unused, so a burst of use a month ago ranks below a menu
 * opened twice this morning.
 */
export const menuUsage = {
    /** @param {{ xmlid?: string }} menu */
    record(menu) {
        if (!menu.xmlid) {
            return;
        }
        const table = read();
        const entry = table[menu.xmlid] || { n: 0, t: 0 };
        table[menu.xmlid] = { n: entry.n + 1, t: Date.now() };
        const xmlids = Object.keys(table);
        if (xmlids.length > MAX_ENTRIES) {
            xmlids
                .sort(
                    (a, b) =>
                        frecency(table[a], Date.now()) - frecency(table[b], Date.now()),
                )
                .slice(0, xmlids.length - MAX_ENTRIES)
                .forEach((xmlid) => delete table[xmlid]);
        }
        write(table);
    },

    clear() {
        try {
            browser.localStorage.removeItem(storageKey());
        } catch {}
    },

    /**
     * The items with a usage entry, most valuable first. Items never opened
     * are absent: this is the recents list, not a full ordering.
     *
     * @template {{ xmlid?: string }} T
     * @param {T[]} items
     * @param {number} [limit]
     * @returns {T[]}
     */
    rank(items, limit = Infinity) {
        const table = read();
        const now = Date.now();
        return items
            .filter((item) => item.xmlid !== undefined && item.xmlid in table)
            .map((item) => ({
                item,
                score: frecency(table[/** @type {string} */ (item.xmlid)], now),
            }))
            .sort((a, b) => b.score - a.score)
            .slice(0, limit)
            .map(({ item }) => item);
    },
};
