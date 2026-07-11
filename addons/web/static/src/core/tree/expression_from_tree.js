// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/expression_from_tree - High-level tree-to-expression conversion with virtual operator elimination */

/** @import { Tree, Options } from "@web/core/tree/condition_tree" */

import { eliminateVirtualOperators } from "@web/core/tree/virtual_operators";

import { constructExpressionFromTree } from "./construct_expression_from_tree.js";

/**
 * Convert a condition tree to a Python expression string.
 * @param {Tree} tree
 * @param {Options} [options]
 * @returns {string}
 * @throws {Error} on trees that have no expression representation
 */
export function expressionFromTree(tree, options = {}) {
    const simplifiedTree = eliminateVirtualOperators(tree, options);
    return constructExpressionFromTree(simplifiedTree, options);
}
