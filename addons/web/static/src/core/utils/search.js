// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/search - Fuzzy text search with consecutive-letter scoring and normalized matching */

import { normalize } from "@web/core/l10n/utils";

/**
 * @param {string} pattern
 * @param {string|string[]} strs
 * @returns {number}
 */
function match(pattern, strs) {
    if (!Array.isArray(strs)) {
        strs = [strs];
    }
    let globalScore = 0;
    for (const str of strs) {
        globalScore = Math.max(globalScore, _match(pattern, str));
    }
    return globalScore;
}

/**
 * This private function computes a score that represent the fact that the
 * string contains the pattern, or not
 *
 * - If the score is 0, the string does not contain the letters of the pattern in
 *   the correct order.
 * - if the score is > 0, it actually contains the letters.
 *
 * Better matches will get a higher score: consecutive letters are better,
 * and a match closer to the beginning of the string is also scored higher.
 *
 * @param {string} pattern
 * @param {string} str
 * @returns {number}
 */
function _match(pattern, str) {
    let totalScore = 0;
    let currentScore = 0;
    let patternIndex = 0;

    pattern = normalize(pattern);
    str = normalize(str);

    const len = str.length;

    for (let i = 0; i < len; i++) {
        if (str[i] === pattern[patternIndex]) {
            patternIndex++;
            currentScore += 100 + currentScore - i / 200;
        } else {
            currentScore = 0;
        }
        totalScore = totalScore + currentScore;
    }

    return patternIndex === pattern.length ? totalScore : 0;
}

/**
 * Return a list of things that matches a pattern, ordered by their 'score' (
 * higher score first). An higher score means that the match is better. For
 * example, consecutive letters are considered a better match.
 *
 * @template T
 * @param {string} pattern
 * @param {T[]} list
 * @param {(element: T) => (string|string[])} fn
 * @returns {T[]}
 */
export function fuzzyLookup(pattern, list, fn) {
    const results = [];
    list.forEach((data) => {
        const score = match(pattern, fn(data));
        if (score > 0) {
            results.push({ score, elem: data });
        }
    });

    // we want better matches first
    results.sort((a, b) => b.score - a.score);

    return results.map((r) => r.elem);
}

// Does `pattern` fuzzy match `string`?
/**
 * @param {string} pattern
 * @param {string} string
 * @returns {boolean}
 */
export function fuzzyTest(pattern, string) {
    return _match(pattern, string) !== 0;
}

/**
 * Performs fuzzy matching using a Levenshtein distance algorithm
 * to find matches within an error margin between a pattern
 * and a list of words.
 *
 * If the pattern is found directly inside an item,
 * it's treated as a perfect match (score 0).
 * Otherwise, the `getScore` function calculates the distance
 * between the pattern and each candidate
 *
 * @param {string} pattern - The string to match.
 * @param {string[]} list - The list of strings to compare against the pattern.
 * @param {number} errorRatio - Controls how many errors can a word have depending of its length.
 * @returns {string[]} The list of the words that matches within a defined number of errors.
 */
export function fuzzyLevenshteinLookup(pattern, list, errorRatio = 3) {
    // Limit the maximum number of errors depending on the pattern length
    // to avoid "overcorrections" into unrelated words. Always allow at
    // least 1 correction so that a short fuzzy query still finds near-matches.
    const maxNbrCorrection = Math.max(1, Math.round(pattern.length / errorRatio));
    const results = [];
    for (const candidate of list) {
        if (candidate.includes(pattern)) {
            // Exact substring — always a match.
            results.push(candidate);
        } else if (candidate.length > pattern.length) {
            // Only attempt Levenshtein on longer candidates: a candidate
            // shorter or equal in length cannot meaningfully contain the
            // pattern as a fuzzy substring, so it would produce false
            // positives (e.g. "ape" for pattern "app").
            const score = getLevenshteinScore(pattern, candidate);
            if (score >= 0 && score <= maxNbrCorrection) {
                results.push(candidate);
            }
        }
    }
    return results;
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
