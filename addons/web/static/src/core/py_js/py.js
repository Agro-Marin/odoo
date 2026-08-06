// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py */

import { ASTType } from "./ast_type.js";
import { BUILTINS } from "./py_builtin.js";
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
 * @type {Map<string, AST>}
 */
const _astCache = new Map();
const _AST_CACHE_MAX = 512;

/**
 * Cached ASTs are handed to every caller of the same expression -- ``Domain``,
 * ``Expression`` and all six ``tree/`` constructors hold onto them -- so the
 * cache is only sound while nobody writes into one. Freezing on the way in
 * makes that an error instead of a convention: an in-place edit now throws
 * where it used to silently poison every later reader of that expression.
 *
 * @template {AST} T
 * @param {T} node
 * @returns {T}
 */
function deepFreeze(node) {
    if (node && typeof node === "object" && !Object.isFrozen(node)) {
        Object.freeze(node);
        for (const child of Object.values(node)) {
            deepFreeze(child);
        }
    }
    return node;
}

/**
 * @param {string} expr
 * @returns { AST }
 */
export function parseExpr(expr) {
    let ast = _astCache.get(expr);
    if (ast) {
        // LRU refresh: re-insert so eviction targets the least recently used
        // entry, not merely the oldest-inserted one.
        _astCache.delete(expr);
        _astCache.set(expr, ast);
        return ast;
    }
    const tokens = tokenize(expr);
    ast = deepFreeze(parse(tokens));
    if (_astCache.size >= _AST_CACHE_MAX) {
        _astCache.delete(_astCache.keys().next().value);
    }
    _astCache.set(expr, ast);
    return ast;
}

export function clearASTCache() {
    _astCache.clear();
}

/**
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
 * @param {unknown} expr an expression, or an already-evaluated modifier value
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
    // Applying `bool` to the result rather than splicing `bool(...)` around the
    // source: the wrapped spelling parsed and cached a second AST for every
    // expression, and reported syntax errors against text the caller never
    // wrote. It also stringified whatever it was handed, which is the only
    // reason a non-string modifier value ever worked -- so keep answering for
    // one, explicitly.
    if (typeof expr !== "string") {
        return BUILTINS.bool(expr);
    }
    return BUILTINS.bool(evaluateExpr(expr, context));
}

/**
 * @param {any} node
 * @param {Set<string>} acc
 */
function collectFreeVariables(node, acc) {
    if (Array.isArray(node)) {
        for (const child of node) {
            collectFreeVariables(child, acc);
        }
        return;
    }
    if (node && typeof node === "object") {
        if (typeof node.type === "number") {
            if (node.type === ASTType.Name) {
                acc.add(node.value);
                return;
            }
            for (const [key, value] of Object.entries(node)) {
                if (key === "type") {
                    continue;
                }
                collectFreeVariables(value, acc);
            }
            return;
        }
        for (const value of Object.values(node)) {
            collectFreeVariables(value, acc);
        }
    }
}

/**
 * @param {string} expr
 * @returns {Set<string>}
 */
export function getExprFreeVariables(expr) {
    const ast = parseExpr(expr);
    const acc = new Set();
    collectFreeVariables(ast, acc);
    return acc;
}
