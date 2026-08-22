// @ts-check
/** @odoo-module native */

/** @typedef {import("../py_js/ast_type.js").AST} AST */
/** @typedef {import("../py_js/ast_type.js").ASTName} ASTName */
/** @typedef {import("../py_js/ast_type.js").ASTFunctionCall} ASTFunctionCall */
/** @typedef {import("../py_js/ast_type.js").ASTUnaryOperator} ASTUnaryOperator */

import { ASTType } from "../py_js/ast_type.js";
import { COMPARATORS, TERM_OPERATORS_NEGATION_EXTENDED } from "./operators.js";

/**
 * @param {AST} ast
 * @returns {ast is ASTFunctionCall}
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
 * @returns {ast is ASTUnaryOperator}
 */
export function isNot(ast) {
    return ast.type === ASTType.UnaryOperator && ast.op === "not";
}

/**
 * @param {AST} ast
 * @returns {AST}
 */
export function not(ast) {
    if (isNot(ast)) {
        return ast.right;
    }
    if (ast.type === ASTType.Boolean) {
        return { ...ast, value: !ast.value };
    }
    if (ast.type === ASTType.BinaryOperator && COMPARATORS.includes(ast.op)) {
        return { ...ast, op: TERM_OPERATORS_NEGATION_EXTENDED[ast.op] };
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
 * @returns {ast is ASTName}
 */
export function isValidPath(ast, options) {
    const getFieldDef = options.getFieldDef || (() => null);
    if (ast.type === ASTType.Name) {
        return getFieldDef(ast.value) != null;
    }
    return false;
}
