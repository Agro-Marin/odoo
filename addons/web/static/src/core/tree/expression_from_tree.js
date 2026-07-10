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
 */
export function expressionFromTree(tree, options = {}) {
    const simplifiedTree = eliminateVirtualOperators(tree, options);
    // Typed ``string | Error``, but Error never surfaces in practice; narrow
    // here rather than widening callers' assumed ``string`` return type.
    return /** @type {string} */ (constructExpressionFromTree(simplifiedTree, options));
}
