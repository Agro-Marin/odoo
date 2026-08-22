// @ts-check
/** @odoo-module native */

import { ASTType } from "./py_js/ast_type.js";
import { evaluateExpr, parseExpr } from "./py_js/py.js";
import { BUILTINS } from "./py_js/py_builtin.js";
import { evaluate } from "./py_js/py_interpreter.js";

/** @typedef {import("./py_js/ast_type.js").AST} AST */

/**
 * @typedef {{
 * lang?: string;
 * tz?: string;
 * uid?: number | false;
 * [key: string]: any;
 * }} Context
 * @typedef {Context | string | undefined} ContextDescription
 */

class InvalidContextError extends Error {}

/**
 * @param {ContextDescription[]} contexts
 * @param {Context} [initialEvaluationContext]
 * @returns {Context}
 */
export function makeContext(contexts, initialEvaluationContext) {
    const evaluationContext = { ...initialEvaluationContext };
    const context = {};
    for (let ctx of contexts) {
        if (ctx !== "") {
            ctx = typeof ctx === "string" ? evaluateExpr(ctx, evaluationContext) : ctx;
            Object.assign(context, ctx);
            Object.assign(evaluationContext, context);
        }
    }
    return context;
}

/**
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
    if (ast.type === ASTType.Chain) {
        return ast.operands.flatMap(getPartialNames);
    }
    if (ast.type === ASTType.ObjLookup) {
        return getPartialNames(ast.obj);
    }
    return [];
}

/**
 * @param {string} _context
 * @param {Context} [evaluationContext={}]
 * @returns {Context}
 */
export function evalPartialContext(_context, evaluationContext = {}) {
    /** @type {any} */
    const ast = parseExpr(_context);
    /** @type {Record<string, any>} */
    const context = {};
    if (ast.type !== ASTType.Dictionary) {
        throw new InvalidContextError(
            `context must be a dict literal, got: ${_context}`,
        );
    }
    for (const key of Object.keys(ast.value)) {
        const value = ast.value[key];
        if (
            getPartialNames(value).some(
                (name) =>
                    !Object.hasOwn(evaluationContext, name) &&
                    !Object.hasOwn(BUILTINS, name),
            )
        ) {
            continue;
        }
        try {
            context[key] = evaluate(value, evaluationContext);
        } catch {}
    }
    return context;
}
