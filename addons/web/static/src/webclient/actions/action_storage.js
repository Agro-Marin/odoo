// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";

const CURRENT_ACTION = "current_action";
const CURRENT_STATE = "current_state";
const CURRENT_LANG = "current_lang";

const RESTORE_KEYS = [CURRENT_ACTION, CURRENT_STATE, CURRENT_LANG];

/**
 * @param {string} key
 * @returns {Object}
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
        } catch {}
        return {};
    }
}

/**
 * @param {string} key
 * @param {string | null} value
 */
function writeRaw(key, value) {
    try {
        if (value === null) {
            browser.sessionStorage.removeItem(key);
        } else {
            browser.sessionStorage.setItem(key, value);
        }
    } catch {}
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
     * @returns {Object}
     */
    getCurrentAction() {
        return readJSON(CURRENT_ACTION);
    },

    /**
     * @param {string} [serializedAction]
     */
    setCurrentAction(serializedAction) {
        writeRaw(CURRENT_ACTION, serializedAction || "{}");
    },

    /**
     * @returns {Object}
     */
    getCurrentState() {
        return readJSON(CURRENT_STATE);
    },

    /** @param {Object} state */
    setCurrentState(state) {
        writeRaw(CURRENT_STATE, JSON.stringify(state));
    },

    /** @returns {string | null} */
    getLang() {
        return readRaw(CURRENT_LANG);
    },

    /** @param {string} lang */
    setLang(lang) {
        writeRaw(CURRENT_LANG, lang);
    },

    clearRestoreCache() {
        for (const key of RESTORE_KEYS) {
            writeRaw(key, null);
        }
    },

    /**
     * @template T
     * @param {{ serializedAction?: string, state: Object }} entry
     * @param {() => T} fn
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
