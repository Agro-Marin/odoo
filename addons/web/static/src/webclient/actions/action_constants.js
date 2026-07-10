// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/action_constants - Constants (dialog sizes, context key regex, embedded action keys, prop shape), error class, and ID parsing for the action service */

/**
 * Kept free of ``@odoo/owl`` / ``@web/*`` imports so the file stays
 * a pure-data leaf in the action_service module graph.
 */

/** Map from Odoo dialog_size context values to Bootstrap modal size classes. */
export const DIALOG_SIZES = {
    "extra-large": "xl",
    large: "lg",
    medium: "md",
    small: "sm",
};

/** Regex matching context keys that should NOT be forwarded between actions. */
export const CTX_KEY_REGEX =
    /^(?:(?:default_|search_default_|show_).+|.+_view_ref|group_by|active_id|active_ids|orderedBy)$/;

/** Context keys added for the embedded actions feature. */
export const EMBEDDED_ACTIONS_CTX_KEYS = [
    "current_embedded_action_id",
    "parent_action_embedded_actions",
    "parent_action_id",
    "from_embedded_action",
];

/**
 * Standard OWL props shape that every action-service-managed component
 * receives. Consumed by `action_service._getActionInfo` (which injects
 * `action`, `actionId`) and by `action_service._updateUI` (which injects
 * `state`, `globalState`).
 *
 * Client actions and view containers spread this into their `static props`
 * to declare the shared baseline alongside their own specific props.
 */
export const standardActionServiceProps = {
    action: Object, // prop added by _getActionInfo
    actionId: { type: Number, optional: true }, // prop added by _getActionInfo
    className: { type: String, optional: true }, // prop added by the ActionContainer
    globalState: { type: Object, optional: true }, // prop added by _updateUI
    state: { type: Object, optional: true }, // prop added by _updateUI
    resId: { type: [Number, Boolean], optional: true },
    updateActionState: { type: Function, optional: true },
};

/**
 * Thrown by `action_service.restore` when the requested controller id
 * is not in the current stack (e.g. a stale breadcrumb link after the
 * stack was rewound, or a manually crafted URL pointing at a nonexistent
 * controller).
 */
export class ControllerNotFoundError extends Error {}

/**
 * Parse a string or number into an array of active record IDs.
 *
 * @param {string|number} ids - comma-separated string or single number
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
