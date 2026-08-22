// @ts-check
/** @odoo-module native */

/**
 * @type {string[]}
 */
const SELF_HANDLED_ATTRS = ["data-bs-toggle", "data-self-handled"];

/** @type {string} */
export const SELF_HANDLED_ATTR = "data-self-handled";

/** @type {string} */
export const SELF_HANDLED_SELECTOR = SELF_HANDLED_ATTRS.map((a) => `[${a}]`).join(",");

/**
 * @type {string}
 */
export const NOT_SELF_HANDLED = SELF_HANDLED_ATTRS.map((a) => `:not([${a}])`).join("");

/**
 * @param {"dropdown" | "modal"} construct
 * @returns {string}
 */
export function selfHandledSelector(construct) {
    return `[${SELF_HANDLED_ATTR}="${construct}"],[data-bs-toggle="${construct}"]`;
}

export const MODAL_TARGET_ATTRS = ["data-modal-target", "data-bs-target"];
