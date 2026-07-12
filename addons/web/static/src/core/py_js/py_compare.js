// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_compare - Shared Python comparison/equality/membership kernel (isLess, isEqual, isIn) used by the interpreter, the max/min builtins and domain membership */

import { EvaluationError, pyTypeName } from "./py_builtin.js";
import { NotSupportedError, PyDate, PyDateTime, PyTime } from "./py_date.js";

/**
 * Order: None < number (boolean) < dict < string < list. Each type maps to
 * an index representing that order.
 *
 * @param {any} val
 * @returns {number} index type
 */
function pytypeIndex(val) {
    switch (typeof val) {
        case "object":
            // None, List, Object, Dict
            return val === null ? 1 : Array.isArray(val) ? 5 : 3;
        case "number":
            return 2;
        case "string":
            return 4;
    }
    throw new EvaluationError(`Unknown type: ${typeof val}`);
}

/**
 * Concrete date/time kind of a Py* temporal value, or null. PyTime extends
 * PyDate, so it must be tested first.
 *
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
 * Python ``<`` semantics: numeric/boolean numeric order, lexicographic list
 * order, cross-type ordering by {@link pytypeIndex}, and a TypeError for
 * incompatible temporal kinds.
 *
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
    // Cross-kind temporal ordering is a TypeError in Python. Without this
    // guard the relational operator would silently compare the incompatible
    // valueOf() scales (date ordinal vs datetime epoch-µs vs time seconds).
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
            // Python lists compare lexicographically element-by-element, NOT
            // by their string coercion: `[2] < [10]` is True. `left < right`
            // would stringify to "2" < "10" → false.
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
 * Python ``==`` semantics: bool/number equivalence, deep list/set/dict
 * comparison, and typed Py* objects' own ``isEqual``.
 *
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
    // Typed Py* objects (PyDate, PyTimeDelta, ...) carry their own equality.
    // Guard with a typeof check so a plain context dict that happens to have an
    // ``isEqual`` key (a data value, not a method) doesn't get called.
    if (left instanceof Object && typeof left.isEqual === "function") {
        return left.isEqual(right);
    }
    if (Array.isArray(left) || Array.isArray(right)) {
        if (!Array.isArray(left) || !Array.isArray(right)) {
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
        // Plain dicts: deep-compare own enumerable keys. If either side exposes
        // a custom ``isEqual`` method it's a typed Py* object, not a dict.
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
 * Python ``in`` semantics: membership uses ``==`` per element for sequences,
 * substring for strings, and key membership for dicts.
 *
 * @param {any} left
 * @param {any} right
 * @returns {boolean}
 */
export function isIn(left, right) {
    if (Array.isArray(right)) {
        // Python ``in`` uses ``==`` per element, so deep-compare (``[1,2] in
        // [[1,2]]`` is True) rather than JS strict ``includes``.
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
