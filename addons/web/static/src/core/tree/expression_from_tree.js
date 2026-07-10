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
    // ``constructExpressionFromTree`` is typed ``string | Error`` but
    // production callers (expression_editor.js) and existing tests treat
    // it as ``string`` — Error returns never surface in practice. Keep
    // the narrowing here; widen the return type if a real Error path
    // ever needs to be handled.
    return /** @type {string} */ (constructExpressionFromTree(simplifiedTree, options));
}
