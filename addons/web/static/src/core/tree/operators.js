// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/operators */

/** @type {Record<string, string>} */
export const TERM_OPERATORS_NEGATION = {
    "<": ">=",
    ">": "<=",
    "<=": ">",
    ">=": "<",
    "=": "!=",
    "!=": "=",
    in: "not in",
    like: "not like",
    ilike: "not ilike",
    "not in": "in",
    "not like": "like",
    "not ilike": "ilike",
};

/** @type {Record<string, string>} */
export const TERM_OPERATORS_NEGATION_EXTENDED = {
    ...TERM_OPERATORS_NEGATION,
    is: "is not",
    "is not": "is",
    "==": "!=",
    "!=": "==",
};

/** @type {string[]} */
export const COMPARATORS = [
    "<",
    "<=",
    ">",
    ">=",
    "in",
    "not in",
    "==",
    "is",
    "!=",
    "is not",
];
