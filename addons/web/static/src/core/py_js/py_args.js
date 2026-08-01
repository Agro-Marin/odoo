// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_args */

import { EvaluationError } from "./py_errors.js";

/**
 * Bind a call's arguments onto ``spec``'s parameter names.
 *
 * Surplus positional arguments and unknown keywords are rejected rather than
 * dropped: an overflow used to land on the string key ``"undefined"``, so
 * ``'abc'.strip('a','b')`` quietly answered ``"bc"`` where CPython raises.
 *
 * @param {any[]} args
 * @param {string[]} spec
 * @param {string} [name] the callee, for the error message
 * @returns {{[name: string]: any}}
 * @throws {EvaluationError} on surplus positionals, unknown or repeated keywords
 */
export function bindArgs(args, spec, name = "function") {
    const last = args.at(-1);
    const hasKwargs = typeof last === "object" && last !== null;
    if (hasKwargs && Array.isArray(last) && odoo.debug) {
        console.warn(
            "bindArgs: trailing argument is an Array, treated as kwargs — a " +
                "direct caller likely omitted the trailing kwargs object.",
        );
    }
    const unnamedArgs = hasKwargs ? args.slice(0, -1) : args;
    if (unnamedArgs.length > spec.length) {
        throw new EvaluationError(
            `${name}() takes at most ${spec.length} argument(s) (${unnamedArgs.length} given)`,
        );
    }
    /** @type {{[name: string]: any}} */
    const kwargs = {};
    for (const [index, val] of unnamedArgs.entries()) {
        kwargs[spec[index]] = val;
    }
    if (hasKwargs) {
        for (const key of Object.keys(last)) {
            if (!spec.includes(key)) {
                throw new EvaluationError(
                    `${name}() got an unexpected keyword argument '${key}'`,
                );
            }
            if (Object.hasOwn(kwargs, key)) {
                throw new EvaluationError(
                    `${name}() got multiple values for argument '${key}'`,
                );
            }
            kwargs[key] = last[key];
        }
    }
    return kwargs;
}
