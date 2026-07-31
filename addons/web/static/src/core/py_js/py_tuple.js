// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_tuple */

/**
 * Python tuples are represented as arrays carrying a non-enumerable marker.
 *
 * The marker lives in its own leaf module because both the interpreter (which
 * sets it) and the comparison helpers (which must not equate a list with a
 * tuple) need it, and those two already import each other transitively.
 */
const PY_TUPLE = Symbol("py.tuple");

/**
 * @param {any[]} array
 * @returns {any[]}
 */
export function markPyTuple(array) {
    Object.defineProperty(array, PY_TUPLE, {
        value: true,
        enumerable: false,
        configurable: true,
    });
    return array;
}

/**
 * @param {any} value
 * @returns {boolean}
 */
export function isPyTuple(value) {
    return Array.isArray(value) && /** @type {any} */ (value)[PY_TUPLE] === true;
}
