// @ts-check
/** @odoo-module native */

import { EvaluationError } from "./py_errors.js";

/**
 * @param {any[]} args
 * @param {string[]} spec
 * @param {string} [name]
 * @returns {{[name: string]: any}}
 * @throws {EvaluationError}
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
