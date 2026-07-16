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
 * INVARIANT / FOOTGUN: the LAST element of ``args`` is treated as the kwargs
 * dict whenever it is any non-null object (arrays included). Every in-tree
 * caller upholds this because the interpreter's ``FunctionCall`` case ALWAYS
 * appends a (possibly empty) plain-object kwargs as the final argument, and the
 * ``Py*.create`` static methods are only ever reached through it. Direct JS
 * callers of the exported ``Py*`` classes MUST append their own trailing kwargs
 * object — e.g. ``PyDateTime.combine(date, time, {})`` — otherwise the last
 * positional (``time``, a Py* object) is silently spread as kwargs and dropped.
 * The debug assertion below flags the one shape that is never a legitimate
 * kwargs — an Array — since that is the most likely accidental misuse.
 *
 * @param {any[]} args
 * @param {string[]} spec
 * @returns {{[name: string]: any}}
 */
export function bindArgs(args, spec) {
    const last = args.at(-1);
    const hasKwargs = typeof last === "object" && last !== null;
    if (hasKwargs && Array.isArray(last) && globalThis.odoo?.debug) {
        // A trailing Array is never a valid kwargs dict (the interpreter always
        // appends a plain object). Reaching here means a direct caller forgot
        // the trailing kwargs object and their last positional is being spread.
        console.warn(
            "bindArgs: trailing argument is an Array, treated as kwargs — a " +
                "direct caller likely omitted the trailing kwargs object.",
        );
    }
    const unnamedArgs = hasKwargs ? args.slice(0, -1) : args;
    // Copy rather than write through: the positional names below were being
    // assigned onto the caller's own kwargs object.
    const kwargs = hasKwargs ? { ...last } : {};
    for (const [index, val] of unnamedArgs.entries()) {
        kwargs[spec[index]] = val;
    }
    return kwargs;
}
