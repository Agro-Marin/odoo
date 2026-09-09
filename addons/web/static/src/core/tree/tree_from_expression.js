// @ts-check
/** @odoo-module native */

import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";

import { constructTreeFromExpression } from "./construct_tree_from_expression.js";

/**
 * @param {string} expression
 * @param {Options} [options]
 * @returns {Tree}
 */
export function treeFromExpression(expression, options = {}) {
    const tree = constructTreeFromExpression(expression, options);
    return introduceVirtualOperators(tree, options);
}
