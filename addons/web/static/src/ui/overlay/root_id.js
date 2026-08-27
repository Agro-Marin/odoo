// @ts-check
/** @odoo-module native */

/**
 * @param {Node | null | undefined} node
 * @returns {string | undefined}
 */
export function rootIdOf(node) {
    return /** @type {ShadowRoot | undefined} */ (node?.getRootNode())?.host?.id;
}
