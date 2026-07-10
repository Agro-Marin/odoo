// @ts-check
/** @odoo-module native */

/** @module @web/core/tree/construct_tree_from_domain - Parses an Odoo domain string into a condition tree structure */

import { Domain } from "@web/core/domain";
import { formatAST } from "@web/core/py_js/py";

import { ASTType } from "../py_js/ast_type.js";
import { addChild, connector, toValue } from "./condition_tree.js";
/** @import { AST } from "@web/core/py_js/py_parser" */
/** @import { DomainRepr } from "@web/core/domain" */
/** @import { Tree } from "./condition_tree.js" */

/**
 * @param {AST[]} ASTs
 * @param {boolean} [distributeNot=false]
 * @param {boolean} [negate=false]
 * @returns {{ tree: Tree, remainingASTs: AST[] }}
 */
function _constructTree(ASTs, distributeNot = false, negate = false) {
    const [firstAST, ...tailASTs] = ASTs;

    if (
        firstAST.type === ASTType.String &&
        /** @type {any} */ (firstAST).value === "!"
    ) {
        return _constructTree(tailASTs, distributeNot, !negate);
    }

    /** @type {any} */
    const tree = { type: firstAST.type === ASTType.String ? "connector" : "condition" };
    if (tree.type === "connector") {
        tree.value = /** @type {any} */ (firstAST).value;
        if (distributeNot && negate) {
            tree.value = tree.value === "&" ? "|" : "&";
            tree.negate = false;
        } else {
            tree.negate = negate;
        }
        tree.children = [];
    } else {
        const [pathAST, operatorAST, valueAST] = /** @type {any} */ (firstAST).value;
        tree.path = toValue(pathAST);
        tree.negate = negate;
        tree.operator = toValue(operatorAST);
        tree.value = toValue(valueAST);
        tree.isProperty = false;
        if (["any", "not any"].includes(tree.operator)) {
            try {
                tree.value = constructTreeFromDomain(
                    formatAST(valueAST),
                    distributeNot,
                );
            } catch {
                tree.value = Array.isArray(tree.value) ? tree.value : [tree.value];
            }
        }
    }
    let remainingASTs = tailASTs;
    if (tree.type === "connector") {
        for (let i = 0; i < 2; i++) {
            const { tree: child, remainingASTs: otherASTs } = _constructTree(
                remainingASTs,
                distributeNot,
                distributeNot && negate,
            );
            remainingASTs = otherASTs;
            addChild(tree, child);
        }
    }
    return { tree, remainingASTs };
}

/**
 * @param {DomainRepr} domain
 * @param {boolean} [distributeNot=false]
 * @returns {Tree}
 */
export function constructTreeFromDomain(domain, distributeNot = false) {
    domain = new Domain(domain);
    const domainAST = domain.ast;
    // @ts-ignore
    const initialASTs = domainAST.value;
    if (!initialASTs.length) {
        return connector("&");
    }
    const { tree } = _constructTree(initialASTs, distributeNot);
    return tree;
}
