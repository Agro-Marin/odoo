// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/utils/unaccent - PostgreSQL-compatible transliteration fold */

import { UNACCENT_REPLACEMENTS, UNACCENT_SOURCES } from "./unaccent_table.js";

/**
 * Lazily-built fold map. Deferred because the overwhelming majority of strings
 * this module sees are pure ASCII and never need it — see the fast path in
 * {@link unaccent}.
 *
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
 * Whether a string contains anything the fold table could act on. Every probed
 * range starts at U+0080, so a string of pure ASCII is always its own fold and
 * can skip the walk entirely.
 *
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
 * Transliterate a string the way PostgreSQL's ``unaccent()`` does.
 *
 * This is the fold the server applies to BOTH operands of an ``ilike`` — in SQL
 * via ``unaccent(...)`` and in ``Model.filtered_domain`` via
 * ``Registry.unaccent_python`` — so it is what any client-side re-implementation
 * of ``ilike`` has to use to select the same records. It goes well beyond
 * stripping combining marks: ``Ø``→``O``, ``æ``→``ae``, ``ß``→``ss``,
 * ``Œ``→``OE``, ``Ł``→``L``, ``₹``→``Rs``, and 1494 more.
 *
 * Note the ORDER this implies at the call site: the server transliterates and
 * only THEN lowercases (``unaccent_python(x).lower()``), because a fold whose
 * replacement is upper-case — ``Æ``→``AE``, ``₹``→``Rs`` — is invisible to a
 * table lookup performed after lowering. Callers wanting a case-insensitive
 * comparison must therefore do ``unaccent(x).toLowerCase()``, not the reverse,
 * and must not lean on a case-insensitive regex flag: no such flag can make a
 * one-to-many fold like ``ß``→``ss`` happen.
 *
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
 * ``unaccent`` + lowercase, in the order the server uses. The single spelling
 * of "fold as ``ilike`` folds", so no call site has to remember the ordering
 * constraint documented above.
 *
 * @param {string} str
 * @returns {string}
 */
export function foldForCaseInsensitiveCompare(str) {
    return unaccent(str).toLowerCase();
}
