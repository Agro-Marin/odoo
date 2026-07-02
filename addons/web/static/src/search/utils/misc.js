// @ts-check
/** @odoo-module native */

/** @module @web/search/utils/misc - Shared constants and helpers for search facet icons, colors, groupable field types, and favorite filters */

/** Icon classes for each search facet type. */
export const FACET_ICONS = {
    filter: "fa-solid fa-filter",
    groupBy: "oi oi-group",
    groupByAsc: "fa-solid fa-arrow-down-1-9",
    groupByDesc: "fa-solid fa-arrow-down-9-1",
    favorite: "fa-solid fa-star",
};

/** Bootstrap color variants for each search facet type. */
export const FACET_COLORS = {
    filter: "primary",
    groupBy: "action",
    favorite: "warning",
};

/** @type {string[]} Field types that support the "Group By" operation. */
export const GROUPABLE_TYPES = [
    "boolean",
    "char",
    "date",
    "datetime",
    "integer",
    "many2one",
    "many2many",
    "selection",
    "tags",
];

/**
 * Open the form view of an ir.filters record to edit a favorite filter.
 * @param {Object} actionService
 * @param {number} resId - id of the ir.filters record
 * @returns {Promise}
 */
export function editFavoriteFilter(actionService, resId) {
    return actionService.doAction({
        type: "ir.actions.act_window",
        res_model: "ir.filters",
        views: [[false, "form"]],
        context: {
            form_view_ref: "base.ir_filters_view_edit_form",
        },
        res_id: resId,
    });
}
