// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { debounce } from "@web/core/utils/timing";
import { session } from "@web/session";

const KEY_PREFIX = "webclient_menu_usage";
const MAX_ENTRIES = 50;
const HALF_LIFE_MS = 7 * 24 * 60 * 60 * 1000;
const SYNC_DELAY_MS = 10_000;

/**
 * @typedef {{ n: number, t: number }} UsageEntry count and last-use timestamp
 * @typedef {Record<string, UsageEntry>} UsageTable keyed by menu xmlid
 */

function storageKey() {
    return `${KEY_PREFIX}:${session.db}:${user.userId}`;
}

/** @param {unknown} value @returns {UsageTable} */
function asTable(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
        return {};
    }
    /** @type {UsageTable} */
    const table = {};
    for (const [xmlid, entry] of Object.entries(value)) {
        const count = Number(/** @type {any} */ (entry)?.n);
        const at = Number(/** @type {any} */ (entry)?.t);
        if (Number.isSafeInteger(count) && count > 0 && Number.isFinite(at)) {
            table[xmlid] = { n: count, t: at > 0 ? at : 0 };
        }
    }
    return table;
}

/** @returns {UsageTable} */
function readLocal() {
    try {
        const raw = browser.localStorage.getItem(storageKey());
        return asTable(raw ? JSON.parse(raw) : null);
    } catch {
        return {};
    }
}

/** @param {UsageTable} table */
function writeLocal(table) {
    try {
        browser.localStorage.setItem(storageKey(), JSON.stringify(table));
    } catch {}
}

/**
 * @param {UsageTable} a
 * @param {UsageTable} b
 * @returns {UsageTable}
 */
export function mergeUsage(a, b) {
    /** @type {UsageTable} */
    const merged = { ...a };
    for (const [xmlid, entry] of Object.entries(b)) {
        const mine = merged[xmlid];
        merged[xmlid] = mine
            ? { n: Math.max(mine.n, entry.n), t: Math.max(mine.t, entry.t) }
            : entry;
    }
    return merged;
}

/**
 * @param {UsageEntry | undefined} entry
 * @param {number} now
 * @returns {number}
 */
function frecency(entry, now) {
    const count = Number(entry?.n) || 0;
    const last = Number(entry?.t) || 0;
    return count * Math.pow(0.5, Math.max(0, now - last) / HALF_LIFE_MS);
}

/**
 * @param {UsageTable} table
 * @param {number} now
 */
function evict(table, now) {
    const xmlids = Object.keys(table);
    if (xmlids.length <= MAX_ENTRIES) {
        return;
    }
    xmlids
        .sort((a, b) => frecency(table[a], now) - frecency(table[b], now))
        .slice(0, xmlids.length - MAX_ENTRIES)
        .forEach((xmlid) => delete table[xmlid]);
}

/**
 * @returns {UsageTable}
 */
function usage() {
    return mergeUsage(asTable(user.settings?.homemenu_usage), readLocal());
}

const sync = debounce(() => {
    Promise.resolve(user.setUserSettings("homemenu_usage", usage())).catch(() => {});
}, SYNC_DELAY_MS);

export const menuUsage = {
    /** @param {{ xmlid?: string }} menu */
    record(menu) {
        if (!menu.xmlid) {
            return;
        }
        const now = Date.now();
        const current = usage();
        const entry = current[menu.xmlid] || { n: 0, t: 0 };
        current[menu.xmlid] = { n: entry.n + 1, t: now };
        evict(current, now);
        writeLocal(current);
        sync();
    },

    /**
     * Forget everything this session knows, both halves -- leaving one behind
     * would let the next read merge it back. Local only, and deliberately: a
     * pending sync is cancelled rather than turned into a write, so this is
     * something a caller can do without reaching the server.
     */
    clear() {
        try {
            browser.localStorage.removeItem(storageKey());
        } catch {}
        sync.cancel?.();
        user.updateUserSettings?.("homemenu_usage", null);
    },

    /**
     * @template {{ xmlid?: string }} T
     * @param {T[]} items
     * @param {number} [limit]
     * @returns {T[]}
     */
    rank(items, limit = Infinity) {
        const current = usage();
        const now = Date.now();
        return items
            .filter((item) => item.xmlid !== undefined && current[item.xmlid])
            .map((item) => ({
                item,
                score: frecency(current[/** @type {string} */ (item.xmlid)], now),
            }))
            .sort((a, b) => b.score - a.score)
            .slice(0, limit)
            .map(({ item }) => item);
    },
};
