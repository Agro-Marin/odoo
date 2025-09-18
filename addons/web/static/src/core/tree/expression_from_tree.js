// @ts-check

/** @module @web/core/tree/expression_from_tree - High-level tree-to-expression conversion with virtual operator elimination */

/** @import { Tree, Options } from "@web/core/tree/condition_tree" */

import { constructExpressionFromTree } from "./construct_expression_from_tree";
import { eliminateVirtualOperators } from "@web/core/tree/virtual_operators";

/**
 * Convert a condition tree to a Python expression string.
 * @param {Tree} tree
 * @param {Options} [options]
 * @returns {string}
 */
export function expressionFromTree(tree, options = {}) {
    const simplifiedTree = eliminateVirtualOperators(tree, options);
    return constructExpressionFromTree(simplifiedTree, options);
}
