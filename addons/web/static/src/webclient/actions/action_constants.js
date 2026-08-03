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
 * The ids come off the url's query string, so they are whatever the caller
 * typed. `Number` accepts far more than a record id: `"1,x,3"` became
 * `[1, NaN, 3]`, and NaN serialises to `null` on its way to the ORM, while an
 * empty segment (`"1,,3"`) became a phantom id 0.
 *
 * A malformed list is corrupt, not partial — acting on the ids that happen to
 * parse would silently narrow the selection — so one bad segment rejects the
 * whole thing. Urls the webclient produces are always plain digits.
 *
 * @param {string|number} ids
 * @returns {number[]}
 */
export function parseActiveIds(ids) {
    if (typeof ids === "number") {
        return Number.isInteger(ids) && ids > 0 ? [ids] : [];
    }
    if (typeof ids !== "string") {
        return [];
    }
    const activeIds = [];
    for (const part of ids.split(",")) {
        if (!/^\d+$/.test(part)) {
            return [];
        }
        const id = Number(part);
        if (id === 0) {
            return [];
        }
        activeIds.push(id);
    }
    return activeIds;
}
