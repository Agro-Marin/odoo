/** @odoo-module native */
export const BASE_CONTAINER_CLASS = "o-paragraph";

export const SUPPORTED_BASE_CONTAINER_NAMES = ["P", "DIV"];

/**
 * @param {string} [nodeName]
 * @returns {string}
 */
export function getBaseContainerSelector(nodeName) {
    if (!nodeName) {
        return baseContainerGlobalSelector;
    }
    nodeName = SUPPORTED_BASE_CONTAINER_NAMES.includes(nodeName) ? nodeName : "P";
    let suffix = "";
    if (nodeName !== "P") {
        suffix = `.${BASE_CONTAINER_CLASS}`;
    }
    return `${nodeName}${suffix}`;
}

export const baseContainerGlobalSelector = `:is(${SUPPORTED_BASE_CONTAINER_NAMES.map(
    (name) => getBaseContainerSelector(name),
).join(",")})`;

/**
 * @param {string} nodeName
 * @param {Document} [document]
 * @returns {HTMLElement}
 */
export function createBaseContainer(nodeName, document) {
    if (!document && window) {
        document = window.document;
    }
    nodeName =
        nodeName && SUPPORTED_BASE_CONTAINER_NAMES.includes(nodeName) ? nodeName : "P";
    const el = document.createElement(nodeName);
    if (nodeName !== "P") {
        el.className = BASE_CONTAINER_CLASS;
    }
    return el;
}
