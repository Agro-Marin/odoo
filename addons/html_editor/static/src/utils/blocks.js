/** @odoo-module native */
import { closestPath, findNode } from "./dom_traversal.js";

const blockTagNames = [
    "ADDRESS",
    "ARTICLE",
    "ASIDE",
    "BLOCKQUOTE",
    "DETAILS",
    "DIALOG",
    "DD",
    "DIV",
    "DL",
    "DT",
    "FIELDSET",
    "FIGCAPTION",
    "FIGURE",
    "FOOTER",
    "FORM",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6",
    "HEADER",
    "HGROUP",
    "HR",
    "LI",
    "MAIN",
    "NAV",
    "OL",
    "P",
    "PRE",
    "SECTION",
    "TABLE",
    "UL",
    "SELECT",
    "OPTION",
    "TR",
    "TD",
    "TBODY",
    "THEAD",
    "TH",
];

const computedStyleDisplayCache = new WeakMap();

export function isBlock(node) {
    if (!node || node.nodeType !== Node.ELEMENT_NODE) {
        return false;
    }
    const tagName = node.nodeName.toUpperCase();
    if (tagName === "BR") {
        return false;
    }
    if (!node.isConnected) {
        return blockTagNames.includes(tagName);
    }
    let display = computedStyleDisplayCache.get(node);
    if (display === undefined) {
        const style = node.ownerDocument.defaultView.getComputedStyle(node);
        display = style.display;
        computedStyleDisplayCache.set(node, display);
    }
    if (display && display !== "none") {
        return !display.includes("inline") && display !== "contents";
    }
    return blockTagNames.includes(tagName);
}

export function closestBlock(node) {
    return findNode(closestPath(node), (node) => isBlock(node));
}
