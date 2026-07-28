// @ts-check
/** @odoo-module native */

/** @module @web/core/l10n/utils/normalize - Unicode normalization, case folding, and accent-insensitive string matching */

import { unaccent } from "./unaccent.js";

/**
 * @typedef {{
 *  match: string;
 *  start: number;
 *  end: number;
 * }} NormalizedMatchResult
 */

/**
 * Normalizes a string for use in comparison.
 *
 * Four passes, and the order between the middle two matters:
 *
 * 1. **NFKC** — collapses compatibility forms, which is how ``𝔖𝔥𝔯𝔢𝔨`` matches
 *    ``Shrek`` and ``㎩`` matches ``Pa``. Those live outside the ranges the
 *    transliteration table covers, so this pass is load-bearing on its own.
 * 2. **Strip combining marks** — works on every script, including the ones the
 *    table says nothing about (kana dakuten, Devanagari, Cyrillic breve).
 * 3. **Transliterate** ({@link unaccent}) — the letters no decomposition can
 *    reach: ``Ø``→``O``, ``æ``→``ae``, ``Þ``→``TH``, ``ŋ``→``n``.
 * 4. **Full case fold** — ``ß`` and ``SS`` compare equal.
 *
 * Steps 2 and 3 are in that order because a character can carry BOTH a
 * combining mark and a stroke: ``Ǿ`` decomposes to ``Ø`` + acute, and only
 * after the acute is gone does the table's ``Ø``→``O`` apply. Transliterating
 * first leaves ``ø``.
 *
 * Step 3 is the same table the server's ``ilike`` folds with (see
 * {@link unaccent}) — one transliteration for the whole client, so a name a
 * user can find by typing it into a search box is a name they can also find
 * with a domain. What this fold adds on top, and ``ilike`` does not have, is
 * NFKC and full case folding: those answer to the user's keyboard rather than
 * to PostgreSQL, and are why the two are still separate entry points.
 *
 * @example
 * normalize("déçûmes") === normalize("DECUMES")
 * normalize("𝔖𝔥𝔯𝔢𝔨") === normalize("Shrek")
 * normalize("Scleßin") === normalize("Sclessin")
 * normalize("Œdipe") === normalize("OeDiPe")
 * normalize("Hawaiʻi") === normalize("Hawai'i")
 *
 * @param {string} str
 * @returns {string}
 */
export function normalize(str) {
    return casefold(unaccent(stripCombiningMarks(str.normalize("NFKC"))));
}

/**
 * Memo of single-codepoint normalizations. The domain is tiny in practice
 * (the distinct codepoints seen in searched strings), while `normalize()`
 * runs four Unicode passes per call — memoizing it turns the per-codepoint
 * normalization done by `normalizedMatch` into a Map lookup.
 *
 * @type {Map<string, string>}
 */
const NORMALIZED_CODEPOINTS = new Map();

/**
 * @param {string} codepoint a single codepoint (one `Array.from(str)` element)
 * @returns {string}
 */
function normalizeCodepoint(codepoint) {
    let normalized = NORMALIZED_CODEPOINTS.get(codepoint);
    if (normalized === undefined) {
        normalized = normalize(codepoint);
        NORMALIZED_CODEPOINTS.set(codepoint, normalized);
    }
    return normalized;
}

/**
 * Core matcher shared by `normalizedMatch` and `normalizedMatches`: finds
 * the first match of the normalized substring starting at codepoint index
 * `fromIndex`, and returns its codepoint index range, or `null`.
 *
 * @param {string[]} normalizedSrc per-codepoint normalizations of the source
 * @param {string[]} normalizedSubstr codepoints of the normalized substring
 * @param {number} fromIndex codepoint index to start searching at
 * @param {number} flattenSrcLength total normalized length of the source
 * @returns {{ startIdx: number, endIdx: number } | null}
 */
function findNormalizedMatch(
    normalizedSrc,
    normalizedSubstr,
    fromIndex,
    flattenSrcLength,
) {
    for (let i = fromIndex; i <= flattenSrcLength - normalizedSubstr.length; ++i) {
        let substrIdx = 0;
        for (let j = 0; i + j < normalizedSrc.length; ++j) {
            const current = normalizedSrc[i + j];
            let allMatched = true;
            for (const c of current) {
                if (substrIdx < normalizedSubstr.length) {
                    if (c !== normalizedSubstr[substrIdx]) {
                        allMatched = false;
                        break;
                    }
                    substrIdx++;
                }
            }
            if (!allMatched) {
                break;
            }
            if (substrIdx >= normalizedSubstr.length) {
                return { startIdx: i, endIdx: i + j + 1 };
            }
        }
    }
    return null;
}

/**
 * Splits the source into codepoints via `Array.from` (not `.split("")`,
 * which breaks unpaired surrogates like "𝔖"). Each codepoint is normalized
 * individually rather than normalizing the whole string, so array indexes
 * stay aligned with the *original* string even though normalization can
 * change string length. `normalizedSrc` may contain empty entries for
 * stripped NFD diacritics, hence `Math.max(x.length, 1)` below.
 *
 * @param {string} src
 */
function prepareSource(src) {
    const srcAsCodepoints = Array.from(src);
    const normalizedSrc = srcAsCodepoints.map(normalizeCodepoint);
    const flattenSrcLength = normalizedSrc.reduce(
        (acc, x) => acc + Math.max(x.length, 1),
        0,
    );
    return { srcAsCodepoints, normalizedSrc, flattenSrcLength };
}

/**
 * Searches for "substr" in "src". The search is performed on normalized strings
 * so that "ce" can match "Cédric".
 *
 * @param {string} src
 * @param {string} substr
 * @returns {NormalizedMatchResult}
 */
export function normalizedMatch(src, substr) {
    if (!substr) {
        return { start: 0, end: 0, match: "" };
    }
    const { srcAsCodepoints, normalizedSrc, flattenSrcLength } = prepareSource(src);
    const normalizedSubstr = Array.from(normalize(substr));
    const found = findNormalizedMatch(
        normalizedSrc,
        normalizedSubstr,
        0,
        flattenSrcLength,
    );
    if (!found) {
        return { start: -1, end: -1, match: "" };
    }
    const start = srcAsCodepoints.slice(0, found.startIdx).join("").length;
    const match = srcAsCodepoints.slice(found.startIdx, found.endIdx).join("");
    const end = start + match.length;
    return { start, end, match };
}

/**
 * Searches for "substr" in "src" as is done in normalizedMatch
 * but returns an array of all successful matches
 *
 * @param {string} src
 * @param {string} substr
 * @returns {NormalizedMatchResult[]}
 */
export function normalizedMatches(src, substr) {
    /** @type {NormalizedMatchResult[]} */
    const matches = [];
    if (!substr) {
        return matches;
    }
    const { srcAsCodepoints, normalizedSrc, flattenSrcLength } = prepareSource(src);
    const normalizedSubstr = Array.from(normalize(substr));
    let fromIndex = 0;
    let charOffset = 0;
    while (fromIndex < srcAsCodepoints.length) {
        const found = findNormalizedMatch(
            normalizedSrc,
            normalizedSubstr,
            fromIndex,
            flattenSrcLength,
        );
        if (!found) {
            break;
        }
        for (let k = fromIndex; k < found.startIdx; ++k) {
            charOffset += srcAsCodepoints[k].length;
        }
        let match = "";
        for (let k = found.startIdx; k < found.endIdx; ++k) {
            match += srcAsCodepoints[k];
        }
        const start = charOffset;
        const end = start + match.length;
        matches.push({ start, end, match });
        charOffset = end;
        fromIndex = found.endIdx;
    }
    return matches;
}

/**
 * Strips the combining marks Unicode does classify as such — every script, not
 * just the ranges the transliteration table covers.
 *
 * `Array.from` is not needed here: `replace` is codepoint-correct for this
 * pattern, and marks are never surrogate pairs in NFD output of BMP text.
 *
 * @param {string} str
 * @returns {string}
 */
function stripCombiningMarks(str) {
    return str.normalize("NFD").replace(/\p{Nonspacing_Mark}/gu, "");
}

/**
 * Normalizes string case for use in comparison.
 *
 * Some characters change length when converted from one case to another. A
 * common example is the German letter "ß," which becomes "SS" when uppercased.
 * This function ensures that these special cases are handled correctly.
 *
 * ⚠ Doesn't preserve "Turkish I"s.
 *
 * @see https://www.w3.org/TR/charmod-norm/#definitionCaseFolding
 * @see https://www.unicode.org/Public/UNIDATA/CaseFolding.txt
 *
 * @example
 * casefold("AAAAAAAA")                 // "aaaaaaaa"
 * casefold("և")                        // "ԵՒ"
 * casefold("Kevin Großkreutz")         // "kevin grosskreutz"
 * casefold("Diyarbakır")               // "diyarbakir"
 * casefold("ß") !== "ß".toLowerCase()  // true
 * casefold("ß") === casefold("SS")     // true
 *
 * @param {string} str
 * @returns {string} lowercase string after "full case folding"
 */
function casefold(str) {
    return str.toLowerCase().toUpperCase().toLowerCase();
}
