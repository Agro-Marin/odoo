// @ts-check
/** @odoo-module native */

import { LruCache } from "@web/core/utils/lru_cache";

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
 * @type {LruCache}
 */
const _astCache = new LruCache(512);

/**
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
    let ast = /** @type {AST | undefined} */ (_astCache.get(expr));
    if (ast) {
        return ast;
    }
    const tokens = tokenize(expr);
    ast = deepFreeze(parse(tokens));
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
 * @param {unknown} expr
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
