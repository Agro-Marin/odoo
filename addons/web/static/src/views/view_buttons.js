// @ts-check
/** @odoo-module native */

import { exprToBoolean } from "@web/core/utils/format/strings";
import { combineModifiers } from "@web/model/relational_model/utils";

export const BUTTON_MODIFIERS = [
    "invisible",
    "column_invisible",
    "readonly",
    "required",
];

export const BUTTON_PRESENTATION = [
    "class",
    "string",
    "icon",
    "title",
    "display",
    "options",
    "disabled",
];

export const BUTTON_CLICK_PARAMS = [
    "name",
    "type",
    "args",
    "block-ui",
    "context",
    "close",
    "cancel-label",
    "confirm",
    "confirm-title",
    "confirm-label",
    "special",
    "effect",
    "help",
    "debounce",
    "noSaveDialog",
];

/**
 * @param {Element} node
 * @returns {Object}
 */
function parseButtonOptions(node) {
    const raw = node.getAttribute("options") || "{}";
    try {
        return JSON.parse(raw);
    } catch (e) {
        throw new Error(`Invalid JSON in button "options" attribute: ${raw}`, {
            cause: e,
        });
    }
}

/**
 * @param {Element} node
 * @returns {{ className: string, disabled: boolean, icon: string|false, title: string|undefined, string: string|undefined, options: Object, display: string, clickParams: Object, column_invisible: string|null, invisible: string|boolean|null|undefined, readonly: string|null, required: string|null, modifiers: Object, attrs: Object }}
 */
export function processButton(node) {
    const withDefault = {
        close: (val) => exprToBoolean(val, false),
        context: (val) => val || "{}",
    };
    const clickParams = {};
    const attrs = {};
    const modifiers = {};
    for (const { name, value } of node.attributes) {
        if (BUTTON_CLICK_PARAMS.includes(name)) {
            clickParams[name] = withDefault[name] ? withDefault[name](value) : value;
        } else if (BUTTON_MODIFIERS.includes(name)) {
            modifiers[name] = value;
        } else if (!BUTTON_PRESENTATION.includes(name)) {
            attrs[name] = value;
        }
    }
    return {
        modifiers,
        className: node.getAttribute("class") || "",
        disabled: exprToBoolean(node.getAttribute("disabled")),
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
