// @ts-check
/** @odoo-module native */

/** @module @web/views/view_buttons - Parses arch button nodes into structured click-param descriptors */

import { exprToBoolean } from "@web/core/utils/format/strings";
import { combineModifiers } from "@web/model/relational_model/utils";

/** Attribute names extracted from `<button>` arch nodes into `clickParams`. */
export const BUTTON_CLICK_PARAMS = [
    "name",
    "type",
    "args",
    "block-ui", // Blocks UI with a spinner until the action is done
    "context",
    "close",
    "cancel-label",
    "confirm",
    "confirm-title",
    "confirm-label",
    "special",
    "effect",
    "help",
    // WOWL SAD: is adding the support for debounce attribute here justified or should we
    // just override compileButton in kanban compiler to add the debounce?
    "debounce",
    // WOWL JPP: is adding the support for not oppening the dialog of confirmation in the settings view
    // This should be refactor someday
    "noSaveDialog",
];

/**
 * Parse the `options` arch attribute as JSON, raising a contextual error.
 *
 * @param {Element} node - the `<button>` XML element from the arch
 * @returns {Object}
 */
function parseButtonOptions(node) {
    const raw = node.getAttribute("options") || "{}";
    try {
        return JSON.parse(raw);
    } catch (e) {
        // Surface the offending arch instead of a bare SyntaxError with a
        // character offset that points into a string the author never sees.
        throw new Error(`Invalid JSON in button "options" attribute: ${raw}`, {
            cause: e,
        });
    }
}

/**
 * Parse a `<button>` XML arch node into a structured descriptor.
 *
 * Splits node attributes into `clickParams` (action-related) and `attrs`
 * (visual/modifier-related), and computes visibility/readonly modifiers.
 *
 * @param {Element} node - the `<button>` XML element from the arch
 * @returns {{ className: string, disabled: boolean, icon: string|false, title: string|undefined, string: string|undefined, options: Object, display: string, clickParams: Object, column_invisible: string|null, invisible: string|null, readonly: string|null, required: string|null, attrs: Object }}
 */
export function processButton(node) {
    const withDefault = {
        close: (val) => exprToBoolean(val, false),
        context: (val) => val || "{}",
    };
    const clickParams = {};
    const attrs = {};
    for (const { name, value } of node.attributes) {
        if (BUTTON_CLICK_PARAMS.includes(name)) {
            clickParams[name] = withDefault[name] ? withDefault[name](value) : value;
        } else {
            attrs[name] = value;
        }
    }
    return {
        className: node.getAttribute("class") || "",
        disabled: !!node.getAttribute("disabled") || false,
        icon: node.getAttribute("icon") || false,
        title: node.getAttribute("title") || undefined,
        string: node.getAttribute("string") || undefined,
        options: parseButtonOptions(node),
        display: node.getAttribute("display") || "selection",
        clickParams,
        column_invisible: node.getAttribute("column_invisible"),
        invisible: combineModifiers(
            node.getAttribute("column_invisible"),
            node.getAttribute("invisible"),
            "OR",
        ),
        readonly: node.getAttribute("readonly"),
        required: node.getAttribute("required"),
        attrs,
    };
}
