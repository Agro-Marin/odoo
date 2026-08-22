// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { formatAST } from "@web/core/py_js/py";

import { ASTType } from "../py_js/ast_type.js";
import { addChild, connector, Expression, toValue } from "./condition_tree.js";
/** @import { AST } from "@web/core/py_js/py_parser" */
/** @import { DomainRepr } from "@web/core/domain" */
/** @import { Tree } from "./condition_tree.js" */

/**
 * @param {AST[]} ASTs
 * @param {boolean} [distributeNot=false]
 * @returns {Tree}
 */
function _constructTree(ASTs, distributeNot = false) {
    let pos = 0;
    /** @type {{ tree: any, remaining: number, childNegate: boolean }[]} */
    const stack = [];
    for (;;) {
        let negate = stack.length ? stack[stack.length - 1].childNegate : false;
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
                if (!(tree.value instanceof Expression) && !Array.isArray(tree.value)) {
                    tree.value = [tree.value];
                }
            }
        }

        /** @type {Tree | null} */
        let node = tree;
        while (stack.length) {
            const frame = stack[stack.length - 1];
            addChild(frame.tree, /** @type {Tree} */ (node));
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
