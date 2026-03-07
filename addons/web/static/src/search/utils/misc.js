// @ts-check

/** @module @web/search/utils/misc - Shared constants for search facet icons, colors, and groupable field types */

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
