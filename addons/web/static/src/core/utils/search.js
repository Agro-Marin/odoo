// @ts-check
/** @odoo-module native */

import { normalize } from "@web/core/l10n/utils";

/**
 * @param {string} normalizedPattern
 * @param {string|string[]} strs
 * @param {boolean} [preNormalized]
 * @returns {number}
 */
function match(normalizedPattern, strs, preNormalized = false) {
    if (!Array.isArray(strs)) {
        strs = [strs];
    }
    let globalScore = 0;
    for (const str of strs) {
        globalScore = Math.max(
            globalScore,
            _match(normalizedPattern, str, preNormalized),
        );
    }
    return globalScore;
}

const MAX_RUN_SCORE = 2 ** 50;

/**
 * @param {string} pattern
 * @param {string} str
 * @param {boolean} [preNormalized]
 * @returns {number}
 */
function _match(pattern, str, preNormalized = false) {
    let totalScore = 0;
    let currentScore = 0;
    let patternIndex = 0;

    if (!preNormalized) {
        str = normalize(str);
    }

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
 * @template T
 * @param {string} pattern
 * @param {T[]} list
 * @param {(element: T) => (string|string[])} fn
 * @param {{ preNormalized?: boolean }} [options]
 * @returns {T[]}
 */
export function fuzzyLookup(pattern, list, fn, { preNormalized = false } = {}) {
    const normalizedPattern = normalize(pattern);
    if (!normalizedPattern) {
        return [...list];
    }
    /** @type {{ score: number, elem: T }[]} */
    const results = [];
    list.forEach((data) => {
        const score = match(normalizedPattern, fn(data), preNormalized);
        if (score > 0) {
            results.push({ score, elem: data });
        }
    });

    results.sort((a, b) => b.score - a.score);

    return results.map((r) => r.elem);
}

/**
 * @param {string} pattern
 * @param {string} string
 * @returns {boolean}
 */
export function fuzzyTest(pattern, string) {
    const normalizedPattern = normalize(pattern);
    return !normalizedPattern || _match(normalizedPattern, string) !== 0;
}

/**
 * @param {string} pattern
 * @param {string[]} list
 * @param {number} errorRatio
 * @returns {string[]}
 */
export function fuzzyLevenshteinLookup(pattern, list, errorRatio = 3) {
    pattern = normalize(pattern);
    const maxNbrCorrection = Math.round(pattern.length / errorRatio);
    const scored = [];
    for (const candidate of list) {
        const norm = normalize(candidate);
        if (norm.includes(pattern)) {
            scored.push({ candidate, score: 0 });
            continue;
        }
        if (Math.abs(norm.length - pattern.length) > maxNbrCorrection) {
            continue;
        }
        const score = getLevenshteinScore(pattern, norm);
        if (score <= maxNbrCorrection) {
            scored.push({ candidate, score });
        }
    }
    scored.sort((a, b) => a.score - b.score);
    return scored.map((r) => r.candidate);
}

/**
 * @param {string} a
 * @param {string} b
 * @returns {number}
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
