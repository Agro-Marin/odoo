// @ts-check
/** @odoo-module native */

import { isEqual } from "./py_compare.js";

/**
 * Set membership and set algebra with CPython's notion of "same member".
 *
 * A JS `Set` keeps members apart by SameValueZero; CPython's set keeps them
 * apart by `hash()`/`__eq__`. The two disagree wherever `isEqual` equates values
 * SameValueZero does not -- `1`/`True`, `0`/`False`, and any two structurally
 * equal objects -- so `new Set(iterable)` builds a set CPython would not:
 *
 *     len(set([1, True]))          CPython 1,  new Set 2
 *     set([1, True]) - set([1])    CPython set(), native difference {true}
 *
 * Every set a py_js expression can observe is built and combined through this
 * module so that the divergence exists in exactly one place: `pyHas`.
 *
 * Cost: the fast path is a plain `Set.has`, O(1). The linear scan is entered
 * only for a boolean, for `0`/`1`, or for an object -- the three shapes that can
 * be equal without being identical. A set of ids or strings never pays it.
 */

/**
 * Is `value` already a member of `set`, by CPython's equality?
 *
 * @param {Set<any>} set
 * @param {any} value
 * @returns {boolean}
 */
export function pyHas(set, value) {
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
 * Add `value` unless an equal member is already there. CPython keeps the member
 * inserted FIRST -- `set([1, True])` is `{1}` and `set([True, 1])` is `{True}` --
 * which is why this never replaces.
 *
 * @param {Set<any>} set
 * @param {any} value
 * @returns {Set<any>}
 */
export function pySetAdd(set, value) {
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
    // `left` is already a py set, so copying it cannot change it -- no need to
    // re-run pyHas over members that have already been folded once.
    const result = new Set(left);
    for (const value of right) {
        pySetAdd(result, value);
    }
    return result;
}

/**
 * CPython's `set_intersection` walks the SMALLER operand and keeps the members
 * it walked, falling back to the right-hand one when the sizes tie or when the
 * right-hand side is an iterable whose size it cannot know. Measured, not
 * guessed:
 *
 *     {1} & {True}      -> {True}      {True} & {1}      -> {1}
 *     {1,2,4} & {True}  -> {True}      {True} & {1,2,4}  -> {True}
 *
 * Only observable when the two operands hold members that are equal but
 * distinguishable -- `1` and `True` -- which is exactly the case that makes a
 * naive implementation disagree with the server.
 *
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
