// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_storage - Single owner of the sessionStorage keys the action manager uses to survive a reload */

import { browser } from "@web/core/browser/browser";

/**
 * The action manager persists three values in ``sessionStorage`` so a page
 * reload (or a new tab opened from an ``ir.actions.act_url``) can rebuild what
 * the user was looking at:
 *
 * | key              | shape                                            |
 * |------------------|--------------------------------------------------|
 * | ``current_action``| JSON of the leaf action (``action._originalAction``) |
 * | ``current_state`` | JSON of the router state (``makeActionState``)   |
 * | ``current_lang``  | plain string — the lang the two above were written under |
 *
 * These used to be read and written as raw string literals from six modules,
 * with two different parse policies: ``current_action`` was parsed inside a
 * ``try``/``catch`` while ``current_state`` was parsed bare. A corrupt
 * ``current_state`` therefore threw inside ``controllersFromState``, and the
 * caller's blanket rescue in ``load_state.js`` degraded the restore to "leaf
 * action, no breadcrumbs" — silently costing the user their back-navigation
 * for what is a purely optional cache.
 *
 * This module is the single owner of that schema. Every read is total: a
 * missing, empty or corrupt value resolves to the same neutral default a
 * missing one would, because all three keys are an optimisation — the URL
 * remains the source of truth.
 */

const CURRENT_ACTION = "current_action";
const CURRENT_STATE = "current_state";
const CURRENT_LANG = "current_lang";

/** Keys that together describe "the action the user was on"; cleared as a unit. */
const RESTORE_KEYS = [CURRENT_ACTION, CURRENT_STATE, CURRENT_LANG];

/**
 * Read a key and parse it as JSON, resolving anything unusable to ``{}``.
 *
 * ``sessionStorage`` is shared with the user (devtools), other tabs of the
 * same session and any extension, and a write can be interrupted — so a
 * malformed value is a normal input here, not an exceptional one.
 *
 * @param {string} key
 * @returns {Object} the parsed object, or ``{}``
 */
function readJSON(key) {
    let raw;
    try {
        raw = browser.sessionStorage.getItem(key);
    } catch {
        return {};
    }
    if (!raw) {
        return {};
    }
    try {
        const parsed = JSON.parse(raw);
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
        console.warn(`Discarding a corrupt "${key}" entry in sessionStorage`);
        try {
            browser.sessionStorage.removeItem(key);
        } catch {
            // Nothing to clean up if storage is unavailable.
        }
        return {};
    }
}

/**
 * @param {string} key
 * @param {string | null} value ``null`` removes the key
 */
function writeRaw(key, value) {
    try {
        if (value === null) {
            browser.sessionStorage.removeItem(key);
        } else {
            browser.sessionStorage.setItem(key, value);
        }
    } catch {
        // Quota exceeded or storage unavailable: the restore cache is
        // best-effort, so losing it must never break the navigation that
        // triggered the write.
    }
}

/** @param {string} key */
function readRaw(key) {
    try {
        return browser.sessionStorage.getItem(key);
    } catch {
        return null;
    }
}

export const actionStorage = {
    /**
     * The last committed action, as a plain object.
     * @returns {Object} ``{}`` when absent or unusable
     */
    getCurrentAction() {
        return readJSON(CURRENT_ACTION);
    },

    /**
     * Store the leaf action. Takes the ALREADY-serialized ``_originalAction``
     * rather than the action object: the action carries non-serializable
     * members (markups, component classes), and ``action_loader`` is what
     * decides what a serializable snapshot of it looks like.
     *
     * @param {string} [serializedAction] ``action._originalAction``
     */
    setCurrentAction(serializedAction) {
        writeRaw(CURRENT_ACTION, serializedAction || "{}");
    },

    /**
     * The last pushed router state, as a plain object.
     * @returns {Object} ``{}`` when absent or unusable
     */
    getCurrentState() {
        return readJSON(CURRENT_STATE);
    },

    /** @param {Object} state a router state (see ``makeActionState``) */
    setCurrentState(state) {
        writeRaw(CURRENT_STATE, JSON.stringify(state));
    },

    /** @returns {string | null} the lang the cached action/state were written under */
    getLang() {
        return readRaw(CURRENT_LANG);
    },

    /** @param {string} lang */
    setLang(lang) {
        writeRaw(CURRENT_LANG, lang);
    },

    /**
     * Drop the whole restore cache. Used when it describes a session that no
     * longer applies — currently a language switch, after which the cached
     * action's translated labels and the state built from them are stale.
     */
    clearRestoreCache() {
        for (const key of RESTORE_KEYS) {
            writeRaw(key, null);
        }
    },

    /**
     * Run ``fn`` with ``current_action``/``current_state`` temporarily set to
     * the given pair, restoring the previous values afterwards.
     *
     * Used to seed a new tab: ``sessionStorage`` is copied into an auxiliary
     * browsing context at the moment it is opened
     * (https://html.spec.whatwg.org/multipage/webstorage.html#webstorage), so
     * the destination window boots from these values — while the originating
     * window must be left exactly as it was.
     *
     * @template T
     * @param {{ serializedAction?: string, state: Object }} entry
     * @param {() => T} fn invoked synchronously; the swap only holds for its duration
     * @returns {T}
     */
    withTemporaryEntry({ serializedAction, state }, fn) {
        const previousAction = readRaw(CURRENT_ACTION);
        const previousState = readRaw(CURRENT_STATE);
        this.setCurrentAction(serializedAction);
        this.setCurrentState(state);
        try {
            return fn();
        } finally {
            writeRaw(CURRENT_ACTION, previousAction);
            writeRaw(CURRENT_STATE, previousState);
        }
    },
};
