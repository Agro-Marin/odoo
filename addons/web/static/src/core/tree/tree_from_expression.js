// @ts-check

/** @module @web/core/tree/tree_from_expression - High-level expression-to-tree conversion with virtual operator introduction */

/** @import { Tree, Options } from "@web/core/tree/condition_tree" */

import { constructTreeFromExpression } from "./construct_tree_from_expression";
import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";

/**
 * Parse a Python expression into a condition tree with virtual operators.
 * @param {string} expression
 * @param {Options} [options]
 * @returns {Tree}
 */
export function treeFromExpression(expression, options = {}) {
    const tree = constructTreeFromExpression(expression, options);
    return introduceVirtualOperators(tree, options);
}
