// @ts-check
/** @odoo-module */

/** @module @web/core/py_js/py_builtin - Python built-in functions (bool, len, set, sorted, etc.) for the JS evaluator */

import { PyDate, PyDateTime, PyRelativeDelta, PyTime, PyTimeDelta } from "./py_date.js";

export class EvaluationError extends Error {}

/**
 * @param {any} iterable
 * @param {Function} func
 */
export function execOnIterable(iterable, func) {
    if (iterable === null) {
        // new Set(null) is fine in js but set(None) (-> new Set(null))
        // is not in Python
        throw new EvaluationError(`value not iterable`);
    }
    if (
        typeof iterable === "object" &&
        !Array.isArray(iterable) &&
        !(iterable instanceof Set)
    ) {
        // dicts are considered as iterable in Python
        iterable = Object.keys(iterable);
    }
    if (typeof iterable?.[Symbol.iterator] !== "function") {
        // rules out undefined and other values not iterable
        throw new EvaluationError(`value not iterable`);
    }
    return func(iterable);
}

export const BUILTINS = {
    /**
     * @param {any} value
     * @returns {boolean}
     */
    bool(value) {
        if (value === undefined || value === null) {
            return false;
        }
        switch (typeof value) {
            case "number":
                return value !== 0;
            case "string":
                return value !== "";
            case "boolean":
                return value;
            case "object":
                if (value.isTrue) {
                    return value.isTrue();
                }
                if (Array.isArray(value)) {
                    return !!value.length;
                }
                if (value instanceof Set) {
                    return !!value.size;
                }
                return Object.keys(value).length !== 0;
        }
        return true;
    },

    set(iterable) {
        if (arguments.length > 2) {
            // we always receive at least one argument: kwargs (return fnValue(...args, kwargs); in FunctionCall case)
            throw new EvaluationError(
                `set expected at most 1 argument, got (${arguments.length - 1})`,
            );
        }
        return execOnIterable(iterable, (iterable) => new Set(iterable));
    },

    max(...args) {
        const values = args.slice(0, -1); // remove kwargs
        if (values.length === 1 && Array.isArray(values[0])) {
            return Math.max(...values[0]);
        }
        return Math.max(...values);
    },

    min(...args) {
        const values = args.slice(0, -1); // remove kwargs
        if (values.length === 1 && Array.isArray(values[0])) {
            return Math.min(...values[0]);
        }
        return Math.min(...values);
    },

    time: {
        strftime(format) {
            return PyDateTime.now().strftime(format);
        },
    },

    /** Return the length of a collection (array, string, Set, or object keys). */
    len(value) {
        if (typeof value === "string" || Array.isArray(value)) {
            return value.length;
        }
        if (value instanceof Set) {
            return value.size;
        }
        if (value && typeof value === "object") {
            return Object.keys(value).length;
        }
        throw new EvaluationError(`object of type '${typeof value}' has no len()`);
    },

    /** Return the absolute value of a number or timedelta. */
    abs(value) {
        if (value instanceof Object && value.negate && value.isTrue) {
            // PyTimeDelta/PyRelativeDelta: negate once if negative
            return value.isTrue() ? value : value.negate();
        }
        return Math.abs(value);
    },

    /** Convert to integer (truncate toward zero). */
    int(value) {
        if (typeof value === "boolean") {
            return value ? 1 : 0;
        }
        if (typeof value === "string") {
            const trimmed = value.trim();
            if (!trimmed || !/^[+-]?\d+$/.test(trimmed)) {
                throw new EvaluationError(`invalid literal for int() with base 10: '${value}'`);
            }
            return parseInt(trimmed, 10);
        }
        return Math.trunc(Number(value));
    },

    /** Convert to float. */
    float(value) {
        if (typeof value === "boolean") {
            return value ? 1.0 : 0.0;
        }
        if (typeof value === "string" && !value.trim()) {
            throw new EvaluationError(`could not convert string to float: '${value}'`);
        }
        const n = Number(value);
        if (isNaN(n)) {
            throw new EvaluationError(`could not convert string to float: '${value}'`);
        }
        return n;
    },

    /** Convert to string. */
    str(value) {
        if (value === null || value === undefined) {
            return "None";
        }
        if (typeof value === "boolean") {
            return value ? "True" : "False";
        }
        return String(value);
    },

    /** Round a number to a given number of decimal places. */
    round(value, ...rest) {
        // rest includes kwargs as last element
        const ndigits = rest.length > 1 ? rest[0] : 0;
        if (ndigits === 0) {
            return Math.round(value);
        }
        const factor = 10 ** ndigits;
        return Math.round(value * factor) / factor;
    },

    context_today() {
        return PyDate.today();
    },

    get current_date() {
        // deprecated: today should be preferred
        return this.today;
    },

    get today() {
        return PyDate.today().strftime("%Y-%m-%d");
    },

    get now() {
        return PyDateTime.now().strftime("%Y-%m-%d %H:%M:%S");
    },

    datetime: {
        time: PyTime,
        timedelta: PyTimeDelta,
        datetime: PyDateTime,
        date: PyDate,
    },

    relativedelta: PyRelativeDelta,

    true: true,
    false: false,
};
