// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/domain_contains_expressions */

/** @typedef {any} Tree */
/** @import { DomainRepr } from "@web/core/domain" */

import { Expression, isTree } from "@web/core/tree/condition_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";

/**
 * @param {Tree} tree
 * @returns {boolean}
 */
function treeContainsExpressions(tree) {
    if (tree.type === "condition") {
        const { path, operator, value } = tree;
        if (isTree(value) && treeContainsExpressions(value)) {
            return true;
        }
        return [path, operator, value].some(
            (v) =>
                v instanceof Expression ||
                (Array.isArray(v) && v.some((w) => w instanceof Expression)),
        );
    }
    for (const child of tree.children) {
        if (treeContainsExpressions(child)) {
            return true;
        }
    }
    return false;
}

/**
 * @param {DomainRepr} domain
 * @returns {boolean|null}
 */
export function domainContainsExpressions(domain) {
    let tree;
    try {
        tree = constructTreeFromDomain(domain);
    } catch {
        return null;
    }
    return treeContainsExpressions(tree);
}
