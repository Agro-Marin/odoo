// @ts-check
/** @odoo-module native */

import { NotSupportedError, PyDate, PyDateTime, PyTime } from "./py_date.js";
import { EvaluationError } from "./py_errors.js";
import { isPyTuple } from "./py_tuple.js";
import { pyTypeName } from "./py_type_name.js";

/**
 * @param {any} val
 * @returns {number}
 */
function pytypeIndex(val) {
    switch (typeof val) {
        case "object":
            return val === null ? 1 : Array.isArray(val) ? 5 : 3;
        case "number":
            return 2;
        case "string":
            return 4;
    }
    throw new EvaluationError(`Unknown type: ${typeof val}`);
}

/**
 * @param {any} value
 * @returns {"date" | "datetime" | "time" | null}
 */
function pyDateKind(value) {
    if (value instanceof PyTime) {
        return "time";
    }
    if (value instanceof PyDate) {
        return "date";
    }
    if (value instanceof PyDateTime) {
        return "datetime";
    }
    return null;
}

/**
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
export function isLess(left, right) {
    if (typeof left === "number" && typeof right === "number") {
        return left < right;
    }
    if (typeof left === "boolean") {
        left = left ? 1 : 0;
    }
    if (typeof right === "boolean") {
        right = right ? 1 : 0;
    }
    const leftDateKind = pyDateKind(left);
    const rightDateKind = pyDateKind(right);
    if (leftDateKind && rightDateKind && leftDateKind !== rightDateKind) {
        throw new NotSupportedError(
            `not supported between instances of '${pyTypeName(left)}' and '${pyTypeName(right)}'`,
        );
    }
    const leftIndex = pytypeIndex(left);
    const rightIndex = pytypeIndex(right);
    if (leftIndex === rightIndex) {
        if (Array.isArray(left) && Array.isArray(right)) {
            const n = Math.min(left.length, right.length);
            for (let i = 0; i < n; i++) {
                if (isLess(left[i], right[i])) {
                    return true;
                }
                if (isLess(right[i], left[i])) {
                    return false;
                }
            }
            return left.length < right.length;
        }
        return left < right;
    }
    return leftIndex < rightIndex;
}

/**
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
export function isEqual(left, right) {
    if (typeof left !== typeof right) {
        if (typeof left === "boolean" && typeof right === "number") {
            return right === (left ? 1 : 0);
        }
        if (typeof left === "number" && typeof right === "boolean") {
            return left === (right ? 1 : 0);
        }
        return false;
    }
    if (left instanceof Object && typeof left.isEqual === "function") {
        return left.isEqual(right);
    }
    if (Array.isArray(left) || Array.isArray(right)) {
        if (!Array.isArray(left) || !Array.isArray(right)) {
            return false;
        }
        if (isPyTuple(left) !== isPyTuple(right)) {
            return false;
        }
        return (
            left.length === right.length && left.every((v, i) => isEqual(v, right[i]))
        );
    }
    if (left instanceof Set || right instanceof Set) {
        if (
            !(left instanceof Set) ||
            !(right instanceof Set) ||
            left.size !== right.size
        ) {
            return false;
        }
        for (const v of left) {
            let found = false;
            for (const w of right) {
                if (isEqual(v, w)) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                return false;
            }
        }
        return true;
    }
    if (
        left !== null &&
        right !== null &&
        typeof left === "object" &&
        typeof right === "object"
    ) {
        if (typeof left.isEqual === "function" || typeof right.isEqual === "function") {
            return false;
        }
        const leftKeys = Object.keys(left);
        const rightKeys = Object.keys(right);
        if (leftKeys.length !== rightKeys.length) {
            return false;
        }
        return leftKeys.every(
            (k) => Object.hasOwn(right, k) && isEqual(left[k], right[k]),
        );
    }
    return left === right;
}

/**
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
export function isIn(left, right) {
    if (Array.isArray(right)) {
        return right.some((x) => isEqual(left, x));
    }
    if (typeof right === "string" && typeof left === "string") {
        return right.includes(left);
    }
    if (right instanceof Set) {
        for (const x of right) {
            if (isEqual(left, x)) {
                return true;
            }
        }
        return false;
    }
    if (right != null && typeof right === "object") {
        return Object.hasOwn(right, left);
    }
    return false;
}
