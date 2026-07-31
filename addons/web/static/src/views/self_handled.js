// @ts-check
/** @odoo-module native */

/** @module @web/views/self_handled - The arch vocabulary for elements the view layer must leave alone */

/**
 * Attributes marking an arch element that handles its own interaction.
 *
 * The view layer consults this in two places: `ViewCompiler` will not turn such
 * an element into an Odoo action button, and a kanban card will not read a click
 * on it as a click on the record.
 *
 * `data-self-handled` is the fork's own spelling and the one arch should use.
 * Its *value* additionally names a construct the compiler knows how to build
 * (`dropdown`, `modal`); any other value — including none — just means "hands
 * off". `data-bs-toggle` is the Bootstrap spelling arch used before, still
 * honoured because databases carry arch nobody has migrated yet; see
 * `_migrate_self_handled_arch` on `ir.ui.view`, which rewrites it in place.
 * Once that has run everywhere, this array loses its first entry and arch stops
 * speaking Bootstrap.
 *
 * @type {string[]}
 */
export const SELF_HANDLED_ATTRS = ["data-bs-toggle", "data-self-handled"];

/** The spelling arch should be written in. @type {string} */
export const SELF_HANDLED_ATTR = "data-self-handled";

/** Matches any self-handled element. @type {string} */
export const SELF_HANDLED_SELECTOR = SELF_HANDLED_ATTRS.map((a) => `[${a}]`).join(",");

/**
 * Suffix excluding every self-handled element, to append to a tag selector.
 * @type {string}
 */
export const NOT_SELF_HANDLED = SELF_HANDLED_ATTRS.map((a) => `:not([${a}])`).join("");

/**
 * Selector for one of the constructs the compiler builds, in either spelling.
 *
 * @param {"dropdown" | "modal"} construct
 * @returns {string}
 */
export function selfHandledSelector(construct) {
    return `[${SELF_HANDLED_ATTR}="${construct}"],[data-bs-toggle="${construct}"]`;
}

/** Where a `modal` control names the modal it drives, in either spelling. */
export const MODAL_TARGET_ATTRS = ["data-modal-target", "data-bs-target"];
