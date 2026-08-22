/** @odoo-module native */

/**
 * The states in which a move, a move line or a picking is settled: nothing about
 * it will change again.
 *
 * The literal was inlined in four components, which is why the fifth copy would
 * have been invisible. Naming it is what makes a divergence detectable.
 */
export const TERMINAL_STATES = ["done", "cancel"];

/** @param {string | false | undefined} state */
export function isTerminalState(state) {
    return TERMINAL_STATES.includes(state);
}

/**
 * The last segment of a package's hierarchical display name.
 *
 * A package reads as `PARENT > CHILD` while it is being handled, and as just
 * `CHILD` once the operation is settled -- there is no ambiguity left to
 * disambiguate at that point.
 *
 * @param {string | false | undefined} displayName
 */
export function leafPackageName(displayName) {
    return displayName ? displayName.split(" > ").pop() : displayName;
}
