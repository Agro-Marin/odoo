// @ts-check
/** @odoo-module native */

/** @module @web/search/utils/misc */

export const FACET_ICONS = {
    filter: "fa-solid fa-filter",
    groupBy: "oi oi-group",
    groupByAsc: "fa-solid fa-arrow-down-1-9",
    groupByDesc: "fa-solid fa-arrow-down-9-1",
    favorite: "fa-solid fa-star",
};

export const FACET_COLORS = {
    filter: "primary",
    groupBy: "action",
    favorite: "warning",
};

/** @type {string[]} */
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
 * @param {Record<string, any>} actionService
 * @param {number} resId
 * @returns {Promise<any>}
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
