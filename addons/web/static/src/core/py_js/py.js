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
 * Bounded cache for parsed ASTs. Expressions in Odoo domains, modifiers, and
 * QWeb conditionals are highly repetitive — the same string (e.g.,
 * "state == 'draft'") is evaluated once per record × per field. Caching the
 * parsed AST eliminates redundant tokenize + parse work (~2,400 calls reduced
 * to ~10 unique parses per 80-row list render).
 *
 * Eviction is FIFO (insertion-order), NOT LRU: a hit does not refresh recency,
 * and eviction always drops the oldest-inserted key. This is intentional — a
 * cache hit is the hottest path here, and true-LRU would add a Map delete+set
 * on every one of those ~2,400 hits/render for a benefit that only materializes
 * once a session exceeds the 512-entry cap (the working set is ~10 expressions,
 * so the cap is effectively never reached). If ``_AST_CACHE_MAX`` is ever
 * lowered enough to be hit in practice, revisit this trade-off.
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
 * Recursively collect the free-variable *root* names referenced by an AST node
 * into ``acc``.
 *
 * A "root name" is the top-level identifier of a reference: for a plain
 * ``ASTName`` it is the name itself; for an attribute access (``ASTObjLookup``,
 * e.g. ``parent.state``) it is the base name (``parent``) — attribute keys are
 * stored as plain strings on the node, never as ``ASTName`` children, so they
 * are naturally excluded. Function-call callees (``bool``, ``len``, …) are
 * ``ASTName`` nodes and therefore included; callers that only care about a
 * bounded universe (e.g. field names) filter those out downstream.
 *
 * The walk is intentionally structural and type-agnostic: any object carrying a
 * numeric ``type`` discriminant is treated as an AST node and all of its
 * non-``type`` properties are traversed (arrays, dictionary/kwargs value maps,
 * and nested nodes alike). This keeps the walker correct across every
 * {@link ASTType} without an exhaustive per-type switch.
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
 * Extract the set of free-variable root names referenced by a Python
 * expression, reusing the bounded AST cache in {@link parseExpr}.
 *
 * Attribute accesses collapse to their base name (``parent.state`` →
 * ``"parent"``, ``context.foo`` → ``"context"``) and subscripts contribute both
 * operands (``a[b]`` → ``"a"``, ``"b"``). Builtins referenced as call callees
 * (``bool``, ``len``) are included; downstream callers filter against their own
 * name universe.
 *
 * @param {string} expr
 * @returns {Set<string>}
 * @throws re-throws the tokenizer/parser error from {@link parseExpr} when
 *  ``expr`` cannot be parsed — callers that want a conservative fallback
 *  should catch it and treat the dependency set as unknown.
 */
export function getExprFreeVariables(expr) {
    const ast = parseExpr(expr);
    const acc = new Set();
    collectFreeVariables(ast, acc);
    return acc;
}
