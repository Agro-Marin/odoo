// @ts-check
/** @odoo-module native */

/** @module @web/core/context - Builds an evaluation context by merging and evaluating Python expressions */

import { ASTType } from "./py_js/ast_type.js";
import { evaluateExpr, parseExpr } from "./py_js/py.js";
import { BUILTINS } from "./py_js/py_builtin.js";
import { evaluate } from "./py_js/py_interpreter.js";

/** @typedef {import("./py_js/ast_type.js").AST} AST */

/**
 * @typedef {{
 *  lang?: string;
 *  tz?: string;
 *  uid?: number | false;
 *  [key: string]: any;
 * }} Context
 * @typedef {Context | string | undefined} ContextDescription
 */

/**
 * Create an evaluated context from an arbitrary list of context representations.
 * The context being built is fed back in to evaluate subsequent expressions.
 *
 * @param {ContextDescription[]} contexts
 * @param {Context} [initialEvaluationContext] optional evaluation context to start from.
 * @returns {Context}
 */
export function makeContext(contexts, initialEvaluationContext) {
    const evaluationContext = { ...initialEvaluationContext };
    const context = {};
    for (let ctx of contexts) {
        if (ctx !== "") {
            ctx = typeof ctx === "string" ? evaluateExpr(ctx, evaluationContext) : ctx;
            Object.assign(context, ctx);
            // Feed accumulated keys back so later expressions can reference earlier ones.
            // e.g. [{ a: 1 }, "{'b': a + 1}", "{'c': b + 1}"] → { a: 1, b: 2, c: 3 }
            Object.assign(evaluationContext, context);
        }
    }
    return context;
}

/**
 * Extract a partial list of variable names found in the AST — incomplete by
 * design, used as a heuristic to skip expressions known to fail evaluation.
 *
 * @param {AST} ast
 * @returns {string[]}
 */
function getPartialNames(ast) {
    if (ast.type === ASTType.Name) {
        return [ast.value];
    }
    if (ast.type === ASTType.UnaryOperator) {
        return getPartialNames(ast.right);
    }
    if (ast.type === ASTType.BooleanOperator || ast.type === ASTType.BinaryOperator) {
        return [...getPartialNames(ast.left), ...getPartialNames(ast.right)];
    }
    if (ast.type === ASTType.ObjLookup) {
        return getPartialNames(ast.obj);
    }
    return [];
}

/**
 * Evaluate a context with an incomplete evaluation context, keeping only
 * keys whose values are static or evaluable with the given context.
 *
 * @param {string} _context
 * @param {Context} [evaluationContext={}]
 * @returns {Context}
 */
export function evalPartialContext(_context, evaluationContext = {}) {
    /** @type {any} */
    const ast = parseExpr(_context);
    /** @type {Record<string, any>} */
    const context = {};
    for (const key in ast.value) {
        const value = ast.value[key];
        if (
            getPartialNames(value).some(
                (name) => !(name in evaluationContext || name in BUILTINS),
            )
        ) {
            continue;
        }
        try {
            context[key] = evaluate(value, evaluationContext);
        } catch {
            // ignore this key as we can't evaluate its value
        }
    }
    return context;
}
