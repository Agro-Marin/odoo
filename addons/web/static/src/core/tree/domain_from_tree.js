// @ts-check
/** @odoo-module native */

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
