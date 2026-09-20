// @ts-check
/** @odoo-module native */

/**
 * @param {Node | null | undefined} node
 * @returns {string}
 */
export function describeNode(node) {
    if (!node) {
        return String(node);
    }
    if (node === document) {
        return "document";
    }
    const el = /** @type {HTMLElement} */ (node);
    const id = el.id ? `#${el.id}` : "";
    const classes = el.classList?.length ? `.${[...el.classList].join(".")}` : "";
    return `${el.tagName?.toLowerCase() ?? node.nodeName}${id}${classes}`;
}
