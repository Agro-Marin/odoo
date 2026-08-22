// @ts-check
/** @odoo-module native */

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
