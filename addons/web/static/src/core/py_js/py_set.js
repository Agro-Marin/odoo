// @ts-check
/** @odoo-module native */

import { isEqual } from "./py_compare.js";

/**
 * @param {Set<any>} set
 * @param {any} value
 * @returns {boolean}
 */
function pyHas(set, value) {
    if (set.has(value)) {
        return true;
    }
    if (typeof value === "boolean") {
        return set.has(value ? 1 : 0);
    }
    if (value === 1 || value === 0) {
        return set.has(value === 1);
    }
    if (value !== null && typeof value === "object") {
        for (const member of set) {
            if (isEqual(member, value)) {
                return true;
            }
        }
    }
    return false;
}

/**
 * @param {Set<any>} set
 * @param {any} value
 * @returns {Set<any>}
 */
function pySetAdd(set, value) {
    if (!pyHas(set, value)) {
        set.add(value);
    }
    return set;
}

/**
 * @param {Iterable<any>} iterable
 * @returns {Set<any>}
 */
export function pySet(iterable) {
    const set = new Set();
    for (const value of iterable) {
        pySetAdd(set, value);
    }
    return set;
}

/**
 * @param {Set<any>} left
 * @param {Iterable<any>} right
 * @returns {Set<any>}
 */
export function pyUnion(left, right) {
    const result = new Set(left);
    for (const value of right) {
        pySetAdd(result, value);
    }
    return result;
}

/**
 * @param {Set<any>} left
 * @param {Iterable<any>} right
 * @returns {Set<any>}
 */
export function pyIntersection(left, right) {
    const walkLeft = right instanceof Set && left.size < right.size;
    const [walked, probed] = walkLeft
        ? [left, right]
        : [right instanceof Set ? right : pySet(right), left];
    const result = new Set();
    for (const value of walked) {
        if (pyHas(probed, value)) {
            pySetAdd(result, value);
        }
    }
    return result;
}

/**
 * @param {Set<any>} left
 * @param {Iterable<any>} right
 * @returns {Set<any>}
 */
export function pyDifference(left, right) {
    const removed = pySet(right);
    const result = new Set();
    for (const value of left) {
        if (!pyHas(removed, value)) {
            result.add(value);
        }
    }
    return result;
}

/**
 * @param {Set<any>} left
 * @param {Iterable<any>} right
 * @returns {Set<any>}
 */
export function pySymmetricDifference(left, right) {
    const other = pySet(right);
    const result = pyDifference(left, other);
    for (const value of other) {
        if (!pyHas(left, value)) {
            pySetAdd(result, value);
        }
    }
    return result;
}
