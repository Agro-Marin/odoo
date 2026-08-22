// @ts-check
/** @odoo-module native */

/** @typedef {import("../py_js/ast_type.js").AST} AST */
/** @import { Tree } from "./condition_tree.js" */
/** @import { Value } from "./condition_tree.js" */
/** @import { Condition } from "./condition_tree.js" */

import { formatAST, parseExpr } from "@web/core/py_js/py";

import { ASTType } from "../py_js/ast_type.js";
import { isBool, isNot } from "./ast_utils.js";
import {
    astFromValue,
    condition,
    Expression,
    FALSE_TREE,
    isTree,
    TRUE_TREE,
} from "./condition_tree.js";

/**
 * @param {AST} ast
 * @returns {AST}
 */
function bool(ast) {
    if (isBool(ast) || isNot(ast) || ast.type === ASTType.Boolean) {
        return ast;
    }
    return {
        type: ASTType.FunctionCall,
        fn: { type: ASTType.Name, value: "bool" },
        args: [ast],
        kwargs: {},
    };
}

/**
 * @param {Tree} tree
 * @param {boolean} [isSubTree=false]
 * @returns {AST[]}
 */
function getASTs(tree, isSubTree = false) {
    const ASTs = [];
    if (tree.type === "condition") {
        if (tree.negate) {
            ASTs.push(toAST("!"));
        }
        ASTs.push({
            type: ASTType.Tuple,
            value: [tree.path, tree.operator, tree.value].map(toAST),
        });
        return ASTs;
    }

    if (tree.type === "complex_condition") {
        const ast = parseExpr(tree.value);
        return getASTs(condition(new Expression(bool(ast)), "=", 1, tree.negate));
    }

    const length = tree.children.length;
    if (length === 0) {
        if (tree.value === "|") {
            return tree.negate ? getASTs(TRUE_TREE) : getASTs(FALSE_TREE);
        } else {
            return tree.negate
                ? getASTs(FALSE_TREE)
                : isSubTree
                  ? getASTs(TRUE_TREE)
                  : [];
        }
    }

    if (tree.negate) {
        ASTs.push(toAST("!"));
    }
    for (let i = 0; i < length - 1; i++) {
        ASTs.push(toAST(tree.value));
    }
    for (const child of tree.children) {
        ASTs.push(...getASTs(child, true));
    }
    return ASTs;
}

/**
 * @param {Value|Tree} value
 * @returns {AST}
 */
function toAST(value) {
    if (isTree(value)) {
        return { type: ASTType.List, value: getASTs(value) };
    }
    return astFromValue(value);
}

/**
 * @param {Tree} tree
 * @returns {string}
 */
export function constructDomainFromTree(tree) {
    return formatAST(toAST(tree));
}
