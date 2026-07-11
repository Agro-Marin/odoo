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
 * Build the tree for the prefix-notation AST list with an index cursor and an
 * explicit connector stack. The previous version copied the tail array at
 * every node (O(N²) in domain size) and recursed once per connector — the
 * normalized ["&", "&", ..., leaf, ...] chain nests to depth O(N) and
 * overflowed the stack on large generated domains.
 *
 * @param {AST[]} ASTs
 * @param {boolean} [distributeNot=false]
 * @returns {Tree}
 */
function _constructTree(ASTs, distributeNot = false) {
    let pos = 0;
    /** @type {{ tree: any, remaining: number, childNegate: boolean }[]} */
    const stack = [];
    for (;;) {
        let negate = stack.length ? stack.at(-1).childNegate : false;
        let firstAST = ASTs[pos++];
        while (
            firstAST.type === ASTType.String &&
            /** @type {any} */ (firstAST).value === "!"
        ) {
            negate = !negate;
            firstAST = ASTs[pos++];
        }

        /** @type {any} */
        const tree = {
            type: firstAST.type === ASTType.String ? "connector" : "condition",
        };
        if (tree.type === "connector") {
            tree.value = /** @type {any} */ (firstAST).value;
            if (distributeNot && negate) {
                tree.value = tree.value === "&" ? "|" : "&";
                tree.negate = false;
            } else {
                tree.negate = negate;
            }
            tree.children = [];
            stack.push({
                tree,
                remaining: 2,
                childNegate: distributeNot && negate,
            });
            continue;
        }

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

        // Attach the completed node upward, popping every connector it fills.
        /** @type {Tree} */
        let node = tree;
        while (stack.length) {
            const frame = stack.at(-1);
            addChild(frame.tree, node);
            frame.remaining--;
            if (frame.remaining > 0) {
                node = null;
                break;
            }
            stack.pop();
            node = frame.tree;
        }
        if (node) {
            return node;
        }
    }
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
    return _constructTree(initialASTs, distributeNot);
}
