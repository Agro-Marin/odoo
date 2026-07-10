// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/ast_utils - AST manipulation helpers for boolean wrapping, negation, and path validation */

/** @typedef {import("../py_js/ast_type.js").AST} AST */
/** @typedef {import("../py_js/ast_type.js").ASTName} ASTName */
/** @typedef {import("../py_js/ast_type.js").ASTFunctionCall} ASTFunctionCall */
/** @typedef {import("../py_js/ast_type.js").ASTUnaryOperator} ASTUnaryOperator */

import { ASTType } from "../py_js/ast_type.js";
import { COMPARATORS, TERM_OPERATORS_NEGATION_EXTENDED } from "./operators.js";

/**
 * @param {AST} ast
 * @returns {ast is ASTFunctionCall} whether the AST is a `bool(...)` call
 */
export function isBool(ast) {
    return (
        ast.type === ASTType.FunctionCall &&
        ast.fn.type === ASTType.Name &&
        ast.fn.value === "bool" &&
        ast.args.length === 1
    );
}

/**
 * @param {AST} ast
 * @returns {ast is ASTUnaryOperator} whether the AST is a `not` unary expression
 */
export function isNot(ast) {
    return ast.type === ASTType.UnaryOperator && ast.op === "not";
}

/**
 * Negate an AST node. Unwraps double negations and flips comparison operators.
 * @param {AST} ast
 * @returns {AST} negated AST
 */
export function not(ast) {
    if (isNot(ast)) {
        return ast.right;
    }
    if (ast.type === ASTType.Boolean) {
        return { ...ast, value: !ast.value };
    }
    if (ast.type === ASTType.BinaryOperator && COMPARATORS.includes(ast.op)) {
        return { ...ast, op: TERM_OPERATORS_NEGATION_EXTENDED[ast.op] }; // do not use this if ast is within a domain context!
    }
    return {
        type: ASTType.UnaryOperator,
        op: "not",
        right: isBool(ast) ? ast.args[0] : ast,
    };
}

/**
 * @param {AST} ast
 * @param {{ getFieldDef?: (name: string) => (Object|null) }} options
 * @returns {ast is ASTName} whether the AST represents a valid field path
 */
export function isValidPath(ast, options) {
    const getFieldDef = options.getFieldDef || (() => null);
    if (ast.type === ASTType.Name) {
        return getFieldDef(ast.value) !== null;
    }
    return false;
}
