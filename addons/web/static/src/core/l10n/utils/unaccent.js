// @ts-check
/** @odoo-module native */

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
 * @param {string} str
 * @param {boolean} [foldAccents=true]
 * @returns {string}
 */
export function foldForCaseInsensitiveCompare(str, foldAccents = true) {
    return (foldAccents ? unaccent(str) : str).toLowerCase();
}
