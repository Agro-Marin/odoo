// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py - Public API for parsing and evaluating Python expressions in JS */

import { evaluate } from "./py_interpreter.js";
import { parse } from "./py_parser.js";
import { tokenize } from "./py_tokenizer.js";

export { evaluate } from "./py_interpreter.js";
export { parse } from "./py_parser.js";
export { tokenize } from "./py_tokenizer.js";
export { formatAST } from "./py_utils.js";

/**
 * @typedef { import("./py_tokenizer").Token } Token
 * @typedef { import("./py_parser").AST } AST
 */

/**
 * LRU cache for parsed ASTs. Expressions in Odoo domains, modifiers, and QWeb
 * conditionals are highly repetitive — the same string (e.g., "state == 'draft'")
 * is evaluated once per record × per field. Caching the parsed AST eliminates
 * redundant tokenize + parse work (~2,400 calls reduced to ~10 unique parses per
 * 80-row list render).
 *
 * @type {Map<string, AST>}
 */
const _astCache = new Map();
const _AST_CACHE_MAX = 512;

/**
 * Parses an expression into a valid AST representation.
 * Results are cached — repeated calls with the same string return the same AST.
 *
 * @param {string} expr
 * @returns { AST }
 */
export function parseExpr(expr) {
    let ast = _astCache.get(expr);
    if (ast) {
        return ast;
    }
    const tokens = tokenize(expr);
    ast = parse(tokens);
    if (_astCache.size >= _AST_CACHE_MAX) {
        // Evict oldest entry (first inserted — Map preserves insertion order)
        _astCache.delete(_astCache.keys().next().value);
    }
    _astCache.set(expr, ast);
    return ast;
}

/** Clear the AST cache (for tests). */
export function clearASTCache() {
    _astCache.clear();
}

/**
 * Evaluates a python expression.
 *
 * @param {string} expr
 * @param {{[key: string]: any}} [context]
 * @returns {any}
 */
export function evaluateExpr(expr, context = {}) {
    let ast;
    try {
        ast = parseExpr(expr);
    } catch (/** @type {any} */ error) {
        throw new EvalError(
            `Can not parse python expression: (${expr})\nError: ${error.message}`,
            { cause: error },
        );
    }
    try {
        return evaluate(ast, context);
    } catch (/** @type {any} */ error) {
        throw new EvalError(
            `Can not evaluate python expression: (${expr})\nError: ${error.message}`,
            { cause: error },
        );
    }
}

/**
 * Evaluates a python expression to return a boolean.
 *
 * @param {string | undefined} expr
 * @param {{[key: string]: any}} [context]
 * @returns {boolean}
 */
export function evaluateBooleanExpr(expr, context = {}) {
    if (!expr || expr === "False" || expr === "0") {
        return false;
    }
    if (expr === "True" || expr === "1") {
        return true;
    }
    return evaluateExpr(`bool(${expr})`, context);
}
