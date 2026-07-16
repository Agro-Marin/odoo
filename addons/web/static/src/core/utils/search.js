// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/search - Fuzzy text search with consecutive-letter scoring and normalized matching */

import { normalize } from "@web/core/l10n/utils";

/**
 * @param {string} normalizedPattern an already-normalized pattern
 * @param {string|string[]} strs
 * @returns {number}
 */
function match(normalizedPattern, strs) {
    if (!Array.isArray(strs)) {
        strs = [strs];
    }
    let globalScore = 0;
    for (const str of strs) {
        globalScore = Math.max(globalScore, _match(normalizedPattern, str));
    }
    return globalScore;
}

/**
 * Cap on the per-run score of {@link _match}. The consecutive bonus doubles
 * the run score on every matched character (exponential growth), so without
 * a cap a run of ~1000 characters overflows to Infinity and every long match
 * compares as equal, degenerating the ranking. 2^50 leaves ranking untouched
 * for any realistic input (the cap is only reached after ~44 consecutive
 * matched characters) while keeping accumulated totals finite.
 */
const MAX_RUN_SCORE = 2 ** 50;

/**
 * Score how well `str` contains the letters of `pattern` in order (0 = no
 * match). Consecutive letters and matches near the start score higher.
 *
 * @param {string} pattern an already-normalized pattern (normalized once at
 *  the entry points instead of once per candidate string)
 * @param {string} str
 * @returns {number}
 */
function _match(pattern, str) {
    let totalScore = 0;
    let currentScore = 0;
    let patternIndex = 0;

    str = normalize(str);

    const len = str.length;

    for (let i = 0; i < len; i++) {
        if (str[i] === pattern[patternIndex]) {
            patternIndex++;
            currentScore = Math.min(
                currentScore + 100 + currentScore - i / 200,
                MAX_RUN_SCORE,
            );
        } else {
            currentScore = 0;
        }
        totalScore = totalScore + currentScore;
    }

    return patternIndex === pattern.length ? totalScore : 0;
}

/**
 * Return `list` filtered to fuzzy matches of `pattern`, ordered by score
 * (higher = better match, e.g. consecutive letters).
 *
 * @template T
 * @param {string} pattern
 * @param {T[]} list
 * @param {(element: T) => (string|string[])} fn
 * @returns {T[]}
 */
export function fuzzyLookup(pattern, list, fn) {
    const normalizedPattern = normalize(pattern);
    /** @type {{ score: number, elem: T }[]} */
    const results = [];
    list.forEach((data) => {
        const score = match(normalizedPattern, fn(data));
        if (score > 0) {
            results.push({ score, elem: data });
        }
    });

    // we want better matches first
    results.sort((a, b) => b.score - a.score);

    return results.map((r) => r.elem);
}

/**
 * @param {string} pattern
 * @param {string} string
 * @returns {boolean}
 */
export function fuzzyTest(pattern, string) {
    return _match(normalize(pattern), string) !== 0;
}

/**
 * Fuzzy-match `pattern` against `list` using Levenshtein distance within an
 * error margin. A direct substring match scores 0 (perfect).
 *
 * @param {string} pattern - The string to match.
 * @param {string[]} list - The list of strings to compare against the pattern.
 * @param {number} errorRatio - Controls how many errors can a word have depending of its length.
 * @returns {string[]} The list of the words that matches within a defined number of errors.
 */
export function fuzzyLevenshteinLookup(pattern, list, errorRatio = 3) {
    // maxNbrCorrection scales with pattern length: longer patterns tolerate
    // more edits.  No minimum — errorRatio=100 on a short pattern yields 0,
    // restricting results to exact substrings only.
    const maxNbrCorrection = Math.round(pattern.length / errorRatio);
    pattern = normalize(pattern);
    const scored = [];
    for (const candidate of list) {
        const norm = normalize(candidate);
        if (norm.includes(pattern)) {
            scored.push({ candidate, score: 0 });
        } else {
            const score = getLevenshteinScore(pattern, norm);
            if (score <= maxNbrCorrection) {
                scored.push({ candidate, score });
            }
        }
    }
    // Best matches first; stable sort preserves input order within ties.
    scored.sort((a, b) => a.score - b.score);
    return scored.map((r) => r.candidate);
}

/**
 * Computes the Levenshtein distance between two strings.
 * Uses a two-row approach: O(min(a,b)) memory instead of O(a*b).
 *
 * @param {string} a
 * @param {string} b
 * @returns {number} The Levenshtein distance between `a` and `b`.
 */
function getLevenshteinScore(a, b) {
    const aLen = a.length;
    const bLen = b.length;
    if (aLen === 0) {
        return bLen;
    }
    if (bLen === 0) {
        return aLen;
    }
    // Ensure b is the shorter string so the row arrays are minimal.
    if (aLen < bLen) {
        return getLevenshteinScore(b, a);
    }
    let prev = new Array(bLen + 1);
    let curr = new Array(bLen + 1);
    for (let j = 0; j <= bLen; j++) {
        prev[j] = j;
    }
    for (let i = 1; i <= aLen; i++) {
        curr[0] = i;
        for (let j = 1; j <= bLen; j++) {
            if (a[i - 1] === b[j - 1]) {
                curr[j] = prev[j - 1];
            } else {
                curr[j] = 1 + Math.min(prev[j], curr[j - 1], prev[j - 1]);
            }
        }
        [prev, curr] = [curr, prev];
    }
    return prev[bLen];
}
