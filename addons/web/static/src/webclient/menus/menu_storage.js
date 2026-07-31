// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_storage */

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

const PAYLOAD_KEY = "webclient_menus";
const VERSION_KEY = "webclient_menus_version";
const HASH_KEY = "webclient_menus_hash";

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
        if (!raw || storedVersion !== session.registry_hash) {
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
            browser.localStorage.setItem(VERSION_KEY, session.registry_hash);
        } catch (error) {
            console.error("Error while storing menus in localStorage", error);
            removeKey(VERSION_KEY);
        }
    },
};
