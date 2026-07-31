// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_constants */

export const DIALOG_SIZES = {
    "extra-large": "xl",
    large: "lg",
    medium: "md",
    small: "sm",
};

export const CTX_KEY_REGEX =
    /^(?:(?:default_|search_default_|show_).+|.+_view_ref|group_by|active_id|active_ids|orderedBy)$/;

export const EMBEDDED_ACTIONS_CTX_KEYS = [
    "current_embedded_action_id",
    "parent_action_embedded_actions",
    "parent_action_id",
    "from_embedded_action",
];

export const standardActionServiceProps = {
    action: Object,
    actionId: { type: Number, optional: true },
    className: { type: String, optional: true },
    globalState: { type: Object, optional: true },
    state: { type: Object, optional: true },
    resId: { type: [Number, Boolean], optional: true },
    updateActionState: { type: Function, optional: true },
};

export class ControllerNotFoundError extends Error {}

export const MAX_ACTION_DEPTH = 20;

/**
 * @param {{ _actionDepth?: number }} [options]
 * @returns {number}
 * @throws {Error}
 */
export function nextActionDepth(options = {}) {
    const depth = (options._actionDepth || 0) + 1;
    if (depth > MAX_ACTION_DEPTH) {
        throw new Error(`Action recursion limit exceeded (max ${MAX_ACTION_DEPTH})`);
    }
    return depth;
}

/**
 * @param {string|number} ids
 * @returns {number[]}
 */
export function parseActiveIds(ids) {
    const activeIds = [];
    if (typeof ids === "string") {
        activeIds.push(...ids.split(",").map(Number));
    } else if (typeof ids === "number") {
        activeIds.push(ids);
    }
    return activeIds;
}
