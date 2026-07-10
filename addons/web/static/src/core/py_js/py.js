// @ts-check
/** @odoo-module native */

/** @module @web/core/py_js/py - Public API for parsing and evaluating Python expressions in JS */

import { ASTType } from "./ast_type.js";
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
 * Bounded cache for parsed ASTs. Domain/modifier/QWeb expressions are highly
 * repetitive (e.g. "state == 'draft'" evaluated once per record × field);
 * caching avoids redundant tokenize+parse work (~2,400 calls reduced to ~10
 * unique parses per 80-row list render).
 *
 * Eviction is FIFO, not LRU: a hit never refreshes recency. True LRU would add
 * a Map delete+set on every one of those hot-path hits for a benefit that
 * never materializes — the ~10-expression working set never hits the 512-entry
 * cap. Revisit if ``_AST_CACHE_MAX`` is ever lowered enough to be hit in practice.
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

/**
 * Recursively collect free-variable *root* names from an AST node into ``acc``.
 *
 * A root name is the top-level identifier: for a plain ``ASTName`` it's the
 * name itself; for attribute access (e.g. ``parent.state``) it's the base name
 * — attribute keys are plain strings, never ``ASTName`` children, so they're
 * excluded automatically. Call callees (``bool``, ``len``, …) are ``ASTName``
 * nodes and included; callers wanting a bounded universe filter downstream.
 *
 * The walk is structural and type-agnostic (dispatches on the numeric ``type``
 * discriminant rather than switching per {@link ASTType}), so it stays correct
 * as node types are added.
 *
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
        // Plain value map (Dictionary.value, FunctionCall.kwargs): traverse values.
        for (const value of Object.values(node)) {
            collectFreeVariables(value, acc);
        }
    }
    // Primitives (strings, numbers, booleans, null) carry no free variables.
}

/**
 * Extract free-variable root names from a Python expression, reusing the
 * bounded AST cache in {@link parseExpr}. Attribute accesses collapse to their
 * base name (``parent.state`` → ``"parent"``); subscripts contribute both
 * operands (``a[b]`` → ``"a"``, ``"b"``).
 *
 * @param {string} expr
 * @returns {Set<string>}
 * @throws re-throws the tokenizer/parser error from {@link parseExpr} on
 *  malformed input — callers wanting a conservative fallback should catch it.
 */
export function getExprFreeVariables(expr) {
    const ast = parseExpr(expr);
    const acc = new Set();
    collectFreeVariables(ast, acc);
    return acc;
}
