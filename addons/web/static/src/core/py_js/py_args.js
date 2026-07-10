// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py_args - Runtime positional/keyword argument binding for Python call evaluation */

/**
 * Bind a call's positional (and trailing kwargs) arguments onto named keys.
 *
 * Pure runtime helper (no parser/AST dependency), used by the interpreter and
 * the ``PyDate``/``PyDateTime``/``PyTime``/``PyRelativeDelta`` constructors.
 * Kept dependency-free so those classes don't have to import the parser (or
 * ``py_utils``, which imports them back — a cycle).
 *
 * @param {any[]} args
 * @param {string[]} spec
 * @returns {{[name: string]: any}}
 */
export function bindArgs(args, spec) {
    const last = args.at(-1);
    const hasKwargs = typeof last === "object" && last !== null;
    const unnamedArgs = hasKwargs ? args.slice(0, -1) : args;
    // Copy rather than write through: the positional names below were being
    // assigned onto the caller's own kwargs object.
    const kwargs = hasKwargs ? { ...last } : {};
    for (const [index, val] of unnamedArgs.entries()) {
        kwargs[spec[index]] = val;
    }
    return kwargs;
}
