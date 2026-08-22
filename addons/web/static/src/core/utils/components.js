// @ts-check
/** @odoo-module native */

import { Component, onError, xml } from "@odoo/owl";

export class ErrorHandler extends Component {
    static template = xml`<t t-slot="default" />`;
    static props = ["onError", "slots"];
    setup() {
        onError((/** @type {Error} */ error) => {
            this.props.onError(error);
        });
    }
}

/**
 * The first DOM element a rendered Owl block produces, or null for a block that
 * rendered no element at all. Private: every caller wants a *component's*
 * element, which is what `getComponentElement` below answers -- exporting the
 * recursion as well only invites a second spelling of the same question.
 *
 * @param {any} node a bdom node, or a component's internal node
 * @returns {HTMLElement | null}
 */
export function getFirstElementOfNode(node) {
    if (!node) {
        return null;
    }
    if (node.el) {
        return node.el.nodeType === Node.ELEMENT_NODE ? node.el : null;
    }
    if (node.bdom || node.child) {
        return getFirstElementOfNode(node.bdom || node.child);
    }
    if (node.children) {
        for (const child of node.children) {
            const el = getFirstElementOfNode(child);
            if (el) {
                return el;
            }
        }
    }
    return null;
}

/**
 * Where a mounted component sits in the DOM. Null before it is mounted.
 *
 * @param {import("@odoo/owl").Component} component
 * @returns {HTMLElement | null}
 */
export function getComponentElement(component) {
    return getFirstElementOfNode(/** @type {any} */ (component).__owl__?.bdom);
}
