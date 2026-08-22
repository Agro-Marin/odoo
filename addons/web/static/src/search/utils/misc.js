// @ts-check
/** @odoo-module native */

/** @type {Record<string, string>} */
export const FACET_ICONS = {
    filter: "fa-solid fa-filter",
    groupBy: "oi oi-group",
    groupByAsc: "fa-solid fa-arrow-down-1-9",
    groupByDesc: "fa-solid fa-arrow-down-9-1",
    favorite: "fa-solid fa-star",
};

/** @type {Record<string, string>} */
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

export const MENU_REGISTRY_VALIDATION = {
    Component: Function,
    groupNumber: { type: Number, optional: true },
    isDisplayed: { type: Function, optional: true },
    "*": true,
};

/**
 * @param {import("@web/core/registry").Registry<any>} registry
 * @param {import("@web/env").OdooEnv} env
 * @returns {Promise<{Component: import("@odoo/owl").ComponentConstructor, groupNumber: number, key: string}[]>}
 */
export async function getDisplayedRegistryItems(registry, env) {
    const entries = registry.getEntries();
    const displayed = await Promise.all(
        entries.map(([, item]) =>
            "isDisplayed" in item ? item.isDisplayed(env) : true,
        ),
    );
    const items = [];
    for (const [index, [key, item]] of entries.entries()) {
        if (displayed[index]) {
            items.push({
                Component: item.Component,
                groupNumber: item.groupNumber,
                key,
            });
        }
    }
    return items;
}

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
