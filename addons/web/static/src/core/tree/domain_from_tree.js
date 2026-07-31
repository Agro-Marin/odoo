// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/domain_from_tree */

/** @import { Tree } from "./condition_tree.js" */

import { constructDomainFromTree } from "./construct_domain_from_tree.js";
import { eliminateVirtualOperators } from "./virtual_operators.js";

/**
 * @param {Tree} tree
 * @returns {string}
 */
export function domainFromTree(tree) {
    const simplifiedTree = eliminateVirtualOperators(tree);
    return constructDomainFromTree(simplifiedTree);
}
