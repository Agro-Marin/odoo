// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_type_name */

import { PyDate, PyDateTime, PyRelativeDelta, PyTime, PyTimeDelta } from "./py_date.js";
import { isPyMapping } from "./py_utils.js";

const PY_TEMPORAL_TYPE_NAMES = new Map(
    /** @type {[Function, string][]} */ ([
        [PyDate, "date"],
        [PyDateTime, "datetime"],
        [PyTime, "time"],
        [PyTimeDelta, "timedelta"],
        [PyRelativeDelta, "relativedelta"],
    ]),
);

/**
 * The Python type name a value reports, for error messages.
 *
 * Split out of ``py_builtin`` so ``py_compare`` can reach it without importing
 * ``py_builtin`` back; see ``py_errors`` for why that cycle mattered.
 *
 * @param {any} value
 * @returns {string}
 */
export function pyTypeName(value) {
    if (value === null || value === undefined) {
        return "NoneType";
    }
    if (Array.isArray(value)) {
        return "list";
    }
    switch (typeof value) {
        case "boolean":
            return "bool";
        case "number":
            return Number.isInteger(value) ? "int" : "float";
        case "string":
            return "str";
        case "object":
            if (value instanceof Set) {
                return "set";
            }
            if (isPyMapping(value)) {
                return "dict";
            }
            return (
                PY_TEMPORAL_TYPE_NAMES.get(value.constructor) ||
                value.constructor?.name ||
                "object"
            );
        default:
            return typeof value;
    }
}
