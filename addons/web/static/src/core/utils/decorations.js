// @ts-check
/** @odoo-module native */

/**
 * @param {string} decoration
 * @returns {string}
 */
export function getClassNameFromDecoration(decoration) {
    if (decoration === "bf") {
        return "fw-bold";
    } else if (decoration === "it") {
        return "fst-italic";
    }
    return `text-${decoration}`;
}

/**
 * @param {Element} rootNode
 * @returns {{ class: string, condition: string }[]}
 */
export function getDecoration(rootNode) {
    const decorations = [];
    for (const name of rootNode.getAttributeNames()) {
        if (name.startsWith("decoration-")) {
            decorations.push({
                class: getClassNameFromDecoration(name.replace("decoration-", "")),
                condition: /** @type {string} */ (rootNode.getAttribute(name)),
            });
        }
    }
    return decorations;
}
