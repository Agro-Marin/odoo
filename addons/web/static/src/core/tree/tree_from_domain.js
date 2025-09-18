// @ts-check

/** @module @web/core/tree/tree_from_domain - High-level domain-to-tree conversion with virtual operator introduction */

/** @import { Tree, Options } from "@web/core/tree/condition_tree" */
/** @import { DomainRepr } from "@web/core/domain" */

import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";

/**
 * Parse a domain into a condition tree with virtual operators.
 * @param {DomainRepr} domain
 * @param {Options} [options]
 * @returns {Tree}
 */
export function treeFromDomain(domain, options = {}) {
    const tree = constructTreeFromDomain(domain, options.distributeNot);
    return introduceVirtualOperators(tree, options);
}
