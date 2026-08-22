// @ts-check
/** @odoo-module native */

/** @import { Tree, Options } from "@web/core/tree/condition_tree" */

import { eliminateVirtualOperators } from "@web/core/tree/virtual_operators";

import { constructExpressionFromTree } from "./construct_expression_from_tree.js";

/**
 * @param {Tree} tree
 * @param {Options} [options]
 * @returns {string}
 * @throws {Error}
 */
export function expressionFromTree(tree, options = {}) {
    const simplifiedTree = eliminateVirtualOperators(tree, options);
    return constructExpressionFromTree(simplifiedTree, options);
}
