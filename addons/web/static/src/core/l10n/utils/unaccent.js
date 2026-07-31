// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/utils/unaccent */

import { UNACCENT_REPLACEMENTS, UNACCENT_SOURCES } from "./unaccent_table.js";

/**
 * @type {Map<string, string> | null}
 */
let foldMap = null;

/** @returns {Map<string, string>} */
function getFoldMap() {
    if (!foldMap) {
        foldMap = new Map();
        const replacements = UNACCENT_REPLACEMENTS.split("\u001f");
        for (let i = 0; i < UNACCENT_SOURCES.length; i++) {
            foldMap.set(UNACCENT_SOURCES[i], replacements[i]);
        }
    }
    return foldMap;
}

/**
 * @param {string} str
 * @returns {boolean}
 */
function needsFold(str) {
    for (let i = 0; i < str.length; i++) {
        if (str.charCodeAt(i) >= 0x80) {
            return true;
        }
    }
    return false;
}

/**
 * @param {string} str
 * @returns {string}
 */
export function unaccent(str) {
    if (!needsFold(str)) {
        return str;
    }
    const map = getFoldMap();
    let out = "";
    for (const char of str) {
        out += map.get(char) ?? char;
    }
    return out;
}

/**
 * Fold a value the way this database's ``ilike`` does.
 *
 * PostgreSQL's ``unaccent`` extension is opt-in (``--unaccent`` defaults to
 * off, and Odoo only issues ``CREATE EXTENSION`` for it when the flag is set),
 * so the server folds accents only when the registry reports the function
 * present -- otherwise ``Field.filter_function`` folds through ``_identity``
 * and ``café`` simply is not ``cafe``. Folding unconditionally here made the
 * client select records the server would not.
 *
 * Unrelated to {@link normalize}, which powers fuzzy *UI* search and should
 * keep folding whatever the database can do.
 *
 * @param {string} str
 * @param {boolean} [foldAccents=true] defaults to the pre-session behaviour
 * @returns {string}
 */
export function foldForCaseInsensitiveCompare(str, foldAccents = true) {
    return (foldAccents ? unaccent(str) : str).toLowerCase();
}
