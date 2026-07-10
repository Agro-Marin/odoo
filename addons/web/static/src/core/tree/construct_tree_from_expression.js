// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/construct_tree_from_expression - Parses a Python expression string into a condition tree structure */

/** @typedef {import("../py_js/ast_type.js").AST} AST */
/** @typedef {import("../py_js/ast_type.js").ASTName} ASTName */
/** @typedef {import("../py_js/ast_type.js").ASTBinaryOperator} ASTBinaryOperator */
/** @typedef {import("../py_js/ast_type.js").ASTFunctionCall} ASTFunctionCall */
/** @import { Tree, Condition, ComplexCondition, Options } from "@web/core/tree/condition_tree" */

import { formatAST, parseExpr } from "@web/core/py_js/py";
import { isNot, isValidPath, not } from "@web/core/tree/ast_utils";
import {
    addChild,
    complexCondition,
    condition,
    connector,
    toValue,
} from "@web/core/tree/condition_tree";
import { COMPARATORS } from "@web/core/tree/operators";

import { ASTType } from "../py_js/ast_type.js";

/** @type {Record<string, string>} Operator exchange map for swapping left/right operands */
const EXCHANGE = {
    "<": ">",
    "<=": ">=",
    ">": "<",
    ">=": "<=",
    "=": "=",
    "!=": "!=",
};

/**
 * Build a boolean-or AST node.
 * @param {AST} left
 * @param {AST} right
 * @returns {AST}
 */
function or(left, right) {
    return { type: ASTType.BooleanOperator, op: "or", left, right };
}

/**
 * Build a boolean-and AST node.
 * @param {AST} left
 * @param {AST} right
 * @returns {AST}
 */
function and(left, right) {
    return { type: ASTType.BooleanOperator, op: "and", left, right };
}

/**
 * Check whether an AST node is a `set()` call (with zero or one argument).
 * @param {AST} ast
 * @returns {boolean}
 */
function isSet(ast) {
    return (
        ast.type === ASTType.FunctionCall &&
        ast.fn.type === ASTType.Name &&
        ast.fn.value === "set" &&
        ast.args.length <= 1
    );
}

/**
 * Like `isValidPath` but also accepts single-element list/tuple ASTs.
 * @param {AST} ast
 * @param {Options} options
 * @returns {boolean|null}
 */
function isValidPath2(ast, options) {
    if (!ast) {
        return null;
    }
    if (
        (ast.type === ASTType.List || ast.type === ASTType.Tuple) &&
        ast.value.length === 1
    ) {
        return isValidPath(ast.value[0], options);
    }
    return isValidPath(ast, options);
}

/**
 * Try to extract a `Condition` from a comparison AST (e.g. `field == value`).
 * Swaps operands if needed so the field path is on the left.
 * @param {ASTBinaryOperator} ast - a comparator AST node
 * @param {Options} options
 * @returns {Condition|null} null if the AST cannot be represented as a simple condition
 */
function _getConditionFromComparator(ast, options) {
    if (["is", "is not"].includes(ast.op)) {
        // we could do something smarter here
        // e.g. if left is a boolean field and right is a boolean
        // we can create a condition based on "="
        return null;
    }

    let operator = ast.op;
    if (operator === "==") {
        operator = "=";
    }

    let left = ast.left;
    let right = ast.right;
    if (isValidPath(left, options) === isValidPath(right, options)) {
        return null;
    }

    if (!isValidPath(left, options)) {
        if (operator in EXCHANGE) {
            const temp = left;
            left = right;
            right = temp;
            operator = EXCHANGE[operator];
        } else {
            return null;
        }
    }

    // left is a validated field path (ASTName) by this point; the swap above
    // loses that refinement for TS, so assert it.
    return condition(/** @type {ASTName} */ (left).value, operator, toValue(right));
}

/**
 * Try to extract a `Condition` from a `set(...).intersection(...)` AST pattern,
 * used for x2many "in"/"not in" checks.
 * @param {ASTFunctionCall} ast - a function-call AST whose fn is a set intersection lookup
 * @param {Options} options
 * @param {boolean} [negate=false]
 * @returns {Condition|null} null if the pattern cannot be decomposed
 */
function _getConditionFromIntersection(ast, options, negate = false) {
    // left/right are reassigned across heterogeneous AST node kinds below
    // (swapped, unwrapped from list/tuple), which TS cannot track — hold as any.
    let left = /** @type {any} */ (ast.fn).obj.args[0];
    let right = /** @type {any} */ (ast.args[0]);

    if (!left) {
        return condition(negate ? 1 : 0, "=", 1);
    }

    // left/right exchange
    if (!isValidPath2(left, options) && !isValidPath2(right, options)) {
        return null;
    }
    if (!isValidPath2(left, options)) {
        const temp = left;
        left = right;
        right = temp;
    }

    if ([ASTType.List, ASTType.Tuple].includes(left.type) && left.value.length === 1) {
        left = left.value[0];
    }

    if (!right) {
        return condition(left.value, negate ? "=" : "!=", false);
    }

    // try to extract the ast of an iterable
    // we only make simple conversions here
    if (isSet(right)) {
        if (!right.args[0]) {
            right = { type: ASTType.List, value: [] };
        } else if ([ASTType.List, ASTType.Tuple].includes(right.args[0].type)) {
            right = right.args[0];
        }
    }

    if (![ASTType.List, ASTType.Tuple].includes(right.type)) {
        return null;
    }

    return condition(left.value, negate ? "not in" : "in", toValue(right));
}

/**
 * Convert a non-connector AST node into a leaf tree node (Condition or ComplexCondition).
 * Handles negation, field paths, set intersections, and comparators.
 * Falls back to `ComplexCondition` when no simple representation exists.
 * @param {AST} ast
 * @param {Options} options
 * @param {boolean} [negate=false]
 * @returns {Tree}
 */
function _leafFromAST(ast, options, negate = false) {
    if (isNot(ast)) {
        return _treeFromAST(ast.right, options, !negate);
    }

    if (ast.type === ASTType.Name && isValidPath(ast, options)) {
        return condition(ast.value, negate ? "=" : "!=", false);
    }

    const astValue = toValue(ast);
    if (["boolean", "number", "string"].includes(typeof astValue)) {
        return condition(astValue ? 1 : 0, "=", 1);
    }

    if (
        ast.type === ASTType.FunctionCall &&
        ast.fn.type === ASTType.ObjLookup &&
        isSet(ast.fn.obj) &&
        ast.fn.key === "intersection"
    ) {
        const tree = _getConditionFromIntersection(ast, options, negate);
        if (tree) {
            return tree;
        }
    }

    if (ast.type === ASTType.BinaryOperator && COMPARATORS.includes(ast.op)) {
        if (negate) {
            return _leafFromAST(not(ast), options);
        }
        const tree = _getConditionFromComparator(ast, options);
        if (tree) {
            return tree;
        }
    }

    // no conclusive/simple way to transform ast in a condition
    return complexCondition(formatAST(negate ? not(ast) : ast));
}

/**
 * Recursively convert an AST into a condition tree.
 * Handles boolean connectors (and/or), ternary expressions, negation,
 * and delegates leaf nodes to `_leafFromAST`.
 * @param {AST} ast
 * @param {Options} options
 * @param {boolean} [negate=false]
 * @returns {Tree}
 */
function _treeFromAST(ast, options, negate = false) {
    if (isNot(ast)) {
        return _treeFromAST(ast.right, options, !negate);
    }

    if (ast.type === ASTType.BooleanOperator) {
        const tree = connector(
            ast.op === "and" ? "&" : "|", // and/or are the only ops that are given type 14 (for now)
        );
        if (options.distributeNot && negate) {
            tree.value = tree.value === "&" ? "|" : "&";
        } else {
            tree.negate = negate;
        }
        const subASTs = [ast.left, ast.right];
        for (const subAST of subASTs) {
            const child = _treeFromAST(
                subAST,
                options,
                options.distributeNot && negate,
            );
            addChild(tree, child);
        }
        return tree;
    }

    if (ast.type === ASTType.If) {
        const newAST = or(
            and(ast.condition, ast.ifTrue),
            and(not(ast.condition), ast.ifFalse),
        );
        return _treeFromAST(newAST, options, negate);
    }

    return _leafFromAST(ast, options, negate);
}

/**
 * Parse a Python expression string into a condition tree.
 * @param {string} expression
 * @param {Options} [options={}]
 * @returns {Tree}
 */
export function constructTreeFromExpression(expression, options = {}) {
    const ast = parseExpr(expression);
    return _treeFromAST(ast, options);
}
