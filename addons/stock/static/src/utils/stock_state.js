/** @odoo-module native */

export const TERMINAL_STATES = ["done", "cancel"];

/** @param {string | false | undefined} state */
export function isTerminalState(state) {
    return TERMINAL_STATES.includes(state);
}

/**
 * @param {string | false | undefined} displayName
 */
export function leafPackageName(displayName) {
    return displayName ? displayName.split(" > ").pop() : displayName;
}
