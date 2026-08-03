// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_storage */

import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { session } from "@web/session";

const PAYLOAD_KEY = "webclient_menus";
const VERSION_KEY = "webclient_menus_version";
const HASH_KEY = "webclient_menus_hash";
const CURRENT_APP_KEY = "menu_id";

/**
 * The cache-validity token. Scoped to the server's registry version AND the
 * current user: the menu tree is filtered by access rights server-side, so on a
 * shared browser a second user must NOT read the first user's cached menus (they
 * can name apps/menus the second user's groups cannot see). `registry_hash`
 * alone is per-server-version, not per-user, so it does not discriminate them.
 * `user.userId` is the canonical id — `session.uid` is stripped from `session`
 * at boot by `@web/core/user`, so reading it here would yield `undefined`.
 *
 * @returns {string}
 */
function cacheVersion() {
    return `${session.registry_hash}:${user.userId}`;
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
        try {
            browser.localStorage.setItem(PAYLOAD_KEY, JSON.stringify(menus));
            if (hash) {
                browser.localStorage.setItem(HASH_KEY, hash);
            } else if (browser.localStorage.getItem(HASH_KEY) !== null) {
                browser.localStorage.removeItem(HASH_KEY);
            }
            browser.localStorage.setItem(VERSION_KEY, cacheVersion());
        } catch (error) {
            console.error("Error while storing menus in localStorage", error);
            removeKey(VERSION_KEY);
        }
    },

    /**
     * The app the tab last opened, in sessionStorage so a second tab starts
     * from the URL rather than from its sibling's app.
     *
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
