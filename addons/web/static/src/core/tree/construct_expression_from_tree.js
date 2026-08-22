// @ts-check
/** @odoo-module native */

/** @typedef {import("../py_js/ast_type.js").AST} AST */
/** @import { Tree } from "@web/core/tree/condition_tree" */
/** @import { Condition, Connector, Options } from "@web/core/tree/condition_tree" */

import { isX2ManyType } from "@web/core/field_types";
import { formatAST, parseExpr } from "@web/core/py_js/py";
import { isValidPath, not } from "@web/core/tree/ast_utils";
import { astFromValue, Expression, isTree } from "@web/core/tree/condition_tree";
import { COMPARATORS, TERM_OPERATORS_NEGATION } from "@web/core/tree/operators";

import { ASTType } from "../py_js/ast_type.js";

/**
 * @param {Condition} condition
 * @returns {Condition}
 */
function getNormalizedCondition(condition) {
    let { operator, negate } = condition;
    if (negate && typeof operator === "string" && TERM_OPERATORS_NEGATION[operator]) {
        operator = TERM_OPERATORS_NEGATION[operator];
        negate = false;
    }
    return { ...condition, operator, negate };
}

/**
 * @param {AST} ast
 * @param {Options} options
 * @returns {boolean}
 */
function isX2ManyPath(ast, options) {
    if (isValidPath(ast, options)) {
        const fieldDef = options.getFieldDef?.(ast.value);
        return (
            !!fieldDef &&
            isX2ManyType(/** @type {Record<string, any>} */ (fieldDef).type)
        );
    }
    return false;
}

/**
 * @param {Tree} tree
 * @returns {tree is Connector}
 */
function isSimpleAnd(tree) {
    return (
        tree.type === "connector" &&
        tree.value === "&" &&
        !tree.negate &&
        tree.children.length === 2
    );
}

/**
 * @param {Tree} tree
 * @param {Options} options
 * @param {boolean} [isRoot=false]
 * @returns {string}
 */
function _constructExpressionFromTree(tree, options, isRoot = false) {
    if (
        tree.type === "connector" &&
        tree.value === "|" &&
        !tree.negate &&
        tree.children.length === 2
    ) {
        const [c1, c2] = tree.children;
        if (isSimpleAnd(c1) && isSimpleAnd(c2)) {
            for (let i = 0; i < 2; i++) {
                const c1Child = c1.children[i];
                const str1 = _constructExpressionFromTree(c1Child, options);
                for (let j = 0; j < 2; j++) {
                    const c2Child = c2.children[j];
                    const str2 = _constructExpressionFromTree(c2Child, options);
                    if (str1 === `not ${str2}` || `not ${str1}` === str2) {
                        const others = [c1.children[1 - i], c2.children[1 - j]];
                        const strs = others.map((c) =>
                            _constructExpressionFromTree(c, options),
                        );
                        const expression = `${strs[0]} if ${str1} else ${strs[1]}`;
                        return isRoot ? expression : `( ${expression} )`;
                    }
                }
            }
        }
    }

    if (tree.type === "connector") {
        const connector = tree.value === "&" ? "and" : "or";
        const subExpressions = tree.children.map((/** @type {Tree} */ c) =>
            _constructExpressionFromTree(c, options),
        );
        if (!subExpressions.length) {
            return connector === "and" ? "1" : "0";
        }
        let expression = subExpressions.join(` ${connector} `);
        if (!isRoot || tree.negate) {
            expression = `( ${expression} )`;
        }
        if (tree.negate) {
            expression = `not ${expression}`;
        }
        return expression;
    }

    if (tree.type === "complex_condition") {
        if (tree.negate) {
            return `not ( ${tree.value} )`;
        }
        if (!isRoot) {
            const ast = parseExpr(tree.value);
            if (ast.type === ASTType.BooleanOperator || ast.type === ASTType.If) {
                return `( ${tree.value} )`;
            }
        }
        return tree.value;
    }

    tree = getNormalizedCondition(tree);
    const { path, operator, value } = tree;

    if (path instanceof Expression && operator === "=" && value === 1) {
        return path.toString();
    }

    if (typeof operator !== "string") {
        throw new Error("Invalid operator");
    }
    const op = operator === "=" ? "==" : operator;
    if (!COMPARATORS.includes(op)) {
        throw new Error("Invalid operator");
    }

    if (path === 0 || path === 1) {
        if (operator !== "=" || value !== 1) {
            throw new Error("Invalid condition");
        }
        return formatAST({ type: ASTType.Boolean, value: Boolean(path) });
    }

    const pathAST = astFromValue(path);
    if (
        typeof path == "string" &&
        isValidPath({ type: ASTType.Name, value: path }, options)
    ) {
        pathAST.type = ASTType.Name;
    }

    if (value === false && ["=", "!="].includes(operator)) {
        return formatAST(operator === "=" ? not(pathAST) : pathAST);
    }

    if (isTree(value)) {
        throw new Error("Invalid value");
    }

    let valueAST = astFromValue(value);
    if (
        ["in", "not in"].includes(operator) &&
        !(value instanceof Expression) &&
        !(
            /** @type {number[]} */ ([ASTType.List, ASTType.Tuple]).includes(
                valueAST.type,
            )
        )
    ) {
        valueAST = { type: ASTType.List, value: [valueAST] };
    }

    if (
        pathAST.type === ASTType.Name &&
        isX2ManyPath(pathAST, options) &&
        ["in", "not in"].includes(operator)
    ) {
        const ast = /** @type {AST} */ ({
            type: ASTType.FunctionCall,
            fn: {
                type: ASTType.ObjLookup,
                obj: {
                    args: [pathAST],
                    type: ASTType.FunctionCall,
                    fn: {
                        type: ASTType.Name,
                        value: "set",
                    },
                },
                key: "intersection",
            },
            args: [valueAST],
        });
        return formatAST(operator === "not in" ? not(ast) : ast);
    }

    return formatAST({
        type: ASTType.BinaryOperator,
        op,
        left: pathAST,
        right: valueAST,
    });
}

/**
 * @param {Tree} tree
 * @param {Options} [options={}]
 * @returns {string}
 * @throws {Error}
 */
export function constructExpressionFromTree(tree, options = {}) {
    return _constructExpressionFromTree(tree, options, true);
}
