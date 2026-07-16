// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/condition_tree - Core tree data structures (conditions, connectors, expressions) and tree manipulation functions */

/** @import { AST } from "@web/core/py_js/py_parser" */
/** @import { DomainRepr } from "@web/core/domain" */

/**
 * @typedef {number|string|boolean|Expression} Atom
 */

/**
 * @typedef {Atom|Atom[]} Value
 */

/**
 * @typedef {Object} Condition
 * @property {"condition"} type
 * @property {Value} path
 * @property {Value} operator
 * @property {Value|Tree} value
 * @property {boolean} negate
 * @property {boolean} [isProperty]
 */

/**
 * @typedef {Object} ComplexCondition
 * @property {"complex_condition"} type
 * @property {string} value expression
 */

/**
 * @typedef {Object} Connector
 * @property {"connector"} type
 * @property {boolean} negate
 * @property {"|"|"&"} value
 * @property {Tree[]} children
 */

/**
 * @typedef {Connector|Condition|ComplexCondition} Tree
 */

/**
 * @typedef {Object} Options
 * @property {(value: Value) => (null|Object)} [getFieldDef]
 * @property {boolean} [distributeNot]
 * @property {boolean} [generateSmartDates] when false, emit literal date/datetime values instead of relative expressions
 */

import { Domain } from "@web/core/domain";
import { formatAST, parseExpr } from "@web/core/py_js/py";
import { toPyValue } from "@web/core/py_js/py_utils";

import { ASTType } from "../py_js/ast_type.js";
export class Expression {
    /**
     * @param {string | AST} ast
     */
    constructor(ast) {
        if (typeof ast === "string") {
            ast = parseExpr(ast);
        }
        this._ast = ast;
        this._expr = formatAST(ast);
    }

    toAST() {
        return this._ast;
    }

    toString() {
        return this._expr;
    }
}

/**
 * @param {string} expr
 * @returns {Expression}
 */
export function expression(expr) {
    return new Expression(expr);
}

/**
 * @param {"|"|"&"} value
 * @param {Tree[]} [children=[]]
 * @param {boolean} [negate=false]
 * @returns {Connector}
 */
export function connector(value, children = [], negate = false) {
    return { type: "connector", value, children, negate };
}

/**
 * @param {string} value
 * @returns {ComplexCondition}
 */
export function complexCondition(value) {
    parseExpr(value);
    return { type: "complex_condition", value };
}

/**
 * @param {Value} path
 * @param {Value} operator
 * @param {Value|Tree} value
 * @param {boolean} [negate=false]
 * @param {boolean} [isProperty=false]
 * @returns {Condition}
 */
export function condition(path, operator, value, negate = false, isProperty = false) {
    return { type: "condition", path, operator, value, negate, isProperty };
}

export const TRUE_TREE = condition(1, "=", 1);
export const FALSE_TREE = condition(0, "=", 1);

/**
 * @param {Value|Tree} value
 * @returns {Value|Tree}
 */
function cloneValue(value) {
    if (value instanceof Expression) {
        // Expression is an immutable value object: `_ast`/`_expr` are set once
        // in the constructor and never mutated, and equality compares the
        // `_expr` string (virtual_operators.js), not instance identity. Reusing
        // the instance is therefore safe and avoids rebuilding it — which
        // re-runs formatAST on every clone, across every operate() pass.
        return value;
    }
    if (Array.isArray(value)) {
        return /** @type {Value} */ (value.map(cloneValue));
    }
    if (isTree(value)) {
        return cloneTree(/** @type {Tree} */ (value));
    }
    return value;
}

/**
 * @param {Tree} tree
 * @returns {Tree}
 */
export function cloneTree(tree) {
    const clone = /** @type {any} */ ({});
    for (const key in tree) {
        clone[key] = cloneValue(/** @type {any} */ (tree)[key]);
    }
    return /** @type {Tree} */ (clone);
}

const areEqualValues = (/** @type {Value} */ value, /** @type {Value} */ otherValue) =>
    formatValue(value) === formatValue(otherValue);

const areEqualArraysOfTrees = (
    /** @type {Tree[]} */ array,
    /** @type {Tree[]} */ otherArray,
) => {
    if (array.length !== otherArray.length) {
        return false;
    }
    for (let i = 0; i < array.length; i++) {
        const elem = array[i];
        const otherElem = otherArray[i];
        if (!areEqualTrees(elem, otherElem)) {
            return false;
        }
    }
    return true;
};

/**
 * @param {any} tree
 * @param {any} otherTree
 * @returns {boolean}
 */
export const areEqualTrees = (tree, otherTree) => {
    if (tree.type !== otherTree.type) {
        return false;
    }
    if (tree.negate !== otherTree.negate) {
        return false;
    }
    if (tree.type === "condition") {
        if (!areEqualValues(tree.path, otherTree.path)) {
            return false;
        }
        if (!areEqualValues(tree.operator, otherTree.operator)) {
            return false;
        }
        if (isTree(tree.value)) {
            if (isTree(otherTree.value)) {
                return areEqualTrees(tree.value, otherTree.value);
            }
            return false;
        } else if (isTree(otherTree.value)) {
            return false;
        }
        if (!areEqualValues(tree.value, otherTree.value)) {
            return false;
        }
        return true;
    }
    if (!areEqualValues(tree.value, otherTree.value)) {
        return false;
    }
    if (tree.type === "complex_condition") {
        return true;
    }
    return areEqualArraysOfTrees(tree.children, otherTree.children);
};

/**
 * @param {any} ast
 * @returns {Value}
 */
export function toValue(ast, isWithinArray = false) {
    if ([ASTType.List, ASTType.Tuple].includes(ast.type) && !isWithinArray) {
        return ast.value.map((/** @type {any} */ v) => toValue(v, true));
    } else if ([ASTType.Number, ASTType.String, ASTType.Boolean].includes(ast.type)) {
        return ast.value;
    } else if (
        ast.type === ASTType.UnaryOperator &&
        ast.op === "-" &&
        ast.right.type === ASTType.Number
    ) {
        return -ast.right.value;
    } else if (ast.type === ASTType.Name && ["false", "true"].includes(ast.value)) {
        return JSON.parse(ast.value);
    } else {
        return new Expression(ast);
    }
}

/**
 * @param {Value} value
 * @returns {AST}
 */
export function astFromValue(value) {
    if (value instanceof Expression) {
        return value.toAST();
    }
    if (Array.isArray(value)) {
        return { type: ASTType.List, value: value.map(astFromValue) };
    }
    return toPyValue(value);
}

/**
 * @param {Value} value
 * @returns {string}
 */
export function formatValue(value) {
    return formatAST(astFromValue(value));
}

/**
 * @param {Value} value
 */
export function normalizeValue(value) {
    return toValue(astFromValue(value)); // no array in array (see isWithinArray)
}

/**
 * @param {any} value
 */
export function isTree(value) {
    return (
        typeof value === "object" &&
        !(value instanceof Domain) &&
        !(value instanceof Expression) &&
        !Array.isArray(value) &&
        value !== null
    );
}

/**
 * @param {Connector} parent
 * @param {Tree} child
 */
export function addChild(parent, child) {
    if (child.type === "connector" && !child.negate && child.value === parent.value) {
        parent.children.push(...child.children);
    } else {
        parent.children.push(child);
    }
}

/**
 * Apply the transformations IN ARRAY ORDER: transformations[0] runs first.
 * Callers whose passes depend on each other's output must order the array
 * accordingly (see the ordering contracts in virtual_operators.js).
 *
 * @param {Function[]} transformations
 * @param {any} transformed
 * @param {...any} fixedParams
 */
export function applyTransformations(transformations, transformed, ...fixedParams) {
    for (const fn of transformations) {
        transformed = fn(transformed, ...fixedParams);
    }
    return transformed;
}

/**
 * @param {Connector} connector
 */
function normalizeConnector(connector) {
    const newTree = { ...connector, children: /** @type {any[]} */ ([]) };
    for (const child of connector.children) {
        addChild(newTree, child);
    }
    if (newTree.children.length === 1) {
        const child = newTree.children[0];
        if (newTree.negate) {
            return { ...child, negate: !child.negate };
        }
        return child;
    }
    return newTree;
}

/**
 * @param {Value} path
 * @param {Options} options
 */
function makeOptions(path, options) {
    return {
        ...options,
        getFieldDef: (/** @type {Value} */ p) => {
            if (typeof path === "string" && typeof p === "string") {
                return options.getFieldDef?.(`${path}.${p}`) || null;
            }
            return null;
        },
    };
}

/**
 * @param {Function} transformation
 * @param {Tree} tree
 * @param {Options} [options={}]
 * @param {"condition"|"connector"|"complex_condition"} [treeType="condition"]
 * @returns {Tree}
 */
export function operate(transformation, tree, options = {}, treeType = "condition") {
    if (tree.type === "connector") {
        const newTree = {
            ...tree,
            children: tree.children.map((c) =>
                operate(transformation, c, options, treeType),
            ),
        };
        if (treeType === "connector") {
            return normalizeConnector(transformation(newTree, options) || newTree);
        }
        return normalizeConnector(newTree);
    }
    const clone = cloneTree(tree);
    if (tree.type === "condition" && isTree(tree.value)) {
        clone.value = operate(
            transformation,
            /** @type {Tree} */ (tree.value),
            makeOptions(tree.path, options),
            treeType,
        );
    }
    if (treeType === tree.type) {
        return transformation(clone, options) || clone;
    }
    return clone;
}

/**
 * @param {Function} transformation
 * @param {number} [N=2]
 */
export function rewriteNConsecutiveChildren(transformation, N = 2) {
    return (/** @type {Connector} */ c, /** @type {Options} */ options) => {
        const children = [];
        const currentChildren = c.children;
        for (let i = 0; i < currentChildren.length; i++) {
            const NconsecutiveChildren = currentChildren.slice(i, i + N);
            let replacement = null;
            if (NconsecutiveChildren.length === N) {
                replacement = transformation(
                    connector(c.value, NconsecutiveChildren),
                    options,
                );
            }
            if (replacement) {
                children.push(replacement);
                i += N - 1;
            } else {
                children.push(NconsecutiveChildren[0]);
            }
        }
        return { ...c, children };
    };
}
