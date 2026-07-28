// @ts-check
/** @odoo-module native */

/** @module @web/webclient/menus/menu_storage - localStorage persistence for the menu tree (payload + registry version + conditional-fetch hash) */

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

/**
 * The menu tree is cached in ``localStorage`` as a trio of keys that must be
 * read and written as a unit:
 *
 * | key                        | meaning                                       |
 * |----------------------------|-----------------------------------------------|
 * | ``webclient_menus``        | JSON payload (includes base64 app icons)      |
 * | ``webclient_menus_version``| ``session.registry_hash`` the payload is for  |
 * | ``webclient_menus_hash``   | ``X-Menus-Hash``, replayed for a 304          |
 *
 * Two ordering rules make the trio safe to resume from, and both are the
 * reason this lives in one module instead of inline in the service:
 *
 * - the **version is written last**: it gates reuse on the next boot, so
 *   writing it first would leave a current stamp over a payload whose write
 *   then failed on quota;
 * - a **failed or corrupt read discards the whole trio**. Before that, one
 *   corrupt value made ``start()`` throw on EVERY subsequent boot — a
 *   permanently blank webclient until the user cleared storage by hand.
 */

const PAYLOAD_KEY = "webclient_menus";
const VERSION_KEY = "webclient_menus_version";
const HASH_KEY = "webclient_menus_hash";

/** @param {string} key */
function removeKey(key) {
    try {
        browser.localStorage.removeItem(key);
    } catch {
        // Storage fully unavailable: nothing to clean up.
    }
}

/** Drop the whole cached trio, so the next boot refetches from scratch. */
function discard() {
    removeKey(PAYLOAD_KEY);
    removeKey(VERSION_KEY);
    removeKey(HASH_KEY);
}

export const menuStorage = {
    /**
     * Read the cached menus.
     *
     * @returns {{ menus: Object | null, raw: string | null, hash: string | undefined }}
     *  ``menus`` is non-null only when the stored payload parses AND was
     *  written for the current ``registry_hash``. ``raw`` is the unparsed
     *  payload — kept so callers can compare a fresh fetch against it without
     *  re-serializing, and so a version-mismatched copy can still be used as a
     *  last resort. ``hash`` feeds the conditional refetch.
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
     * Parse a stored payload, discarding the whole trio when it is corrupt
     * (interrupted write, extension, manual edit).
     *
     * @param {string} raw
     * @returns {Object | null} the parsed menus, or null when corrupt
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
     * Persist a payload and its server hash.
     *
     * @param {Object} menus
     * @param {string} [hash] server-side hash of ``menus`` (``X-Menus-Hash``)
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
