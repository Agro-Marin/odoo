// @ts-check
/** @odoo-module native */

import { unaccent } from "./unaccent.js";

/**
 * @typedef {{
 * match: string;
 * start: number;
 * end: number;
 * }} NormalizedMatchResult
 */

/**
 * @param {string} str
 * @returns {string}
 */
export function normalize(str) {
    return casefold(unaccent(stripCombiningMarks(str.normalize("NFKC"))));
}

/**
 * @type {Map<string, string>}
 */
const NORMALIZED_CODEPOINTS = new Map();

/**
 * @param {string} codepoint
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
 * @param {string[]} normalizedSrc
 * @param {string[]} normalizedSubstr
 * @param {number} fromIndex
 * @param {number} flattenSrcLength
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
 * @param {string} src
 * @param {string} substr
 * @returns {NormalizedMatchResult}
 */
export function normalizedMatch(src, substr) {
    const normalizedSubstr = Array.from(normalize(substr || ""));
    if (!normalizedSubstr.length) {
        return { start: 0, end: 0, match: "" };
    }
    const { srcAsCodepoints, normalizedSrc, flattenSrcLength } = prepareSource(src);
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
 * @param {string} src
 * @param {string} substr
 * @returns {NormalizedMatchResult[]}
 */
export function normalizedMatches(src, substr) {
    /** @type {NormalizedMatchResult[]} */
    const matches = [];
    const normalizedSubstr = Array.from(normalize(substr || ""));
    if (!normalizedSubstr.length) {
        return matches;
    }
    const { srcAsCodepoints, normalizedSrc, flattenSrcLength } = prepareSource(src);
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
 * @param {string} str
 * @returns {string}
 */
function stripCombiningMarks(str) {
    return str.normalize("NFD").replace(/\p{Nonspacing_Mark}/gu, "");
}

/**
 * @param {string} str
 * @returns {string}
 */
function casefold(str) {
    return str.toLowerCase().toUpperCase().toLowerCase();
}
