// @ts-check
/** @odoo-module */

/** @module @web/core/tree/domain_from_tree - High-level tree-to-domain conversion with virtual operator elimination */

/** @import { Tree } from "./condition_tree.js" */

import { constructDomainFromTree } from "./construct_domain_from_tree.js";
import { eliminateVirtualOperators } from "./virtual_operators.js";

/**
 * Convert a condition tree to an Odoo domain string.
 * @param {Tree} tree
 * @returns {string}
 */
export function domainFromTree(tree) {
    const simplifiedTree = eliminateVirtualOperators(tree);
    return constructDomainFromTree(simplifiedTree);
}
