// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { session } from "@web/session";

const PAYLOAD_KEY = "webclient_menus";
const VERSION_KEY = "webclient_menus_version";
const HASH_KEY = "webclient_menus_hash";
const CURRENT_APP_KEY = "menu_id";

/**
 * @returns {string | undefined}
 */
function cacheVersion() {
    return session.menus_cache_version;
}

/**
 * @param {string | null} storedVersion
 * @returns {boolean}
 */
function isForeignUserVersion(storedVersion) {
    const separatorIndex = (storedVersion || "").lastIndexOf(":");
    if (separatorIndex === -1) {
        return false;
    }
    return (
        /** @type {string} */ (storedVersion).slice(separatorIndex + 1) !==
        String(session.uid ?? user.userId)
    );
}

/** @param {string} key */
function removeKey(key) {
    try {
        browser.localStorage.removeItem(key);
    } catch {}
}

function discard() {
    removeKey(PAYLOAD_KEY);
    removeKey(VERSION_KEY);
    removeKey(HASH_KEY);
}

export const menuStorage = {
    /**
     * @returns {{ menus: Object | null, raw: string | null, hash: string | undefined }}
     */
    read() {
        let raw, storedVersion, hash;
        try {
            raw = browser.localStorage.getItem(PAYLOAD_KEY);
            storedVersion = browser.localStorage.getItem(VERSION_KEY);
            hash = browser.localStorage.getItem(HASH_KEY) || undefined;
        } catch {
            return { menus: null, raw: null, hash: undefined };
        }
        if (!raw || storedVersion !== cacheVersion()) {
            if (raw && isForeignUserVersion(storedVersion)) {
                return { menus: null, raw: null, hash: undefined };
            }
            return { menus: null, raw, hash };
        }
        return { menus: this.parse(raw), raw, hash };
    },

    /**
     * @param {string} raw
     * @returns {Object | null}
     */
    parse(raw) {
        try {
            return JSON.parse(raw);
        } catch {
            console.warn(
                "Corrupt webclient_menus in localStorage; discarding the cached copy",
            );
            discard();
            return null;
        }
    },

    /**
     * @param {Object} menus
     * @param {string} [hash]
     */
    write(menus, hash) {
        const version = cacheVersion();
        if (!version) {
            return;
        }
        try {
            browser.localStorage.setItem(PAYLOAD_KEY, JSON.stringify(menus));
            if (hash) {
                browser.localStorage.setItem(HASH_KEY, hash);
            } else if (browser.localStorage.getItem(HASH_KEY) !== null) {
                browser.localStorage.removeItem(HASH_KEY);
            }
            browser.localStorage.setItem(VERSION_KEY, version);
        } catch (error) {
            console.error("Error while storing menus in localStorage", error);
            removeKey(VERSION_KEY);
        }
    },

    /**
     * @returns {number}
     */
    readCurrentApp() {
        try {
            return Number(browser.sessionStorage.getItem(CURRENT_APP_KEY)) || 0;
        } catch {
            return 0;
        }
    },

    /** @param {number|string} appId */
    writeCurrentApp(appId) {
        try {
            browser.sessionStorage.setItem(CURRENT_APP_KEY, String(appId));
        } catch {}
    },
};
