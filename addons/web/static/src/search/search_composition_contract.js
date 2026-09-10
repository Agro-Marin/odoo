// @ts-check
/** @odoo-module native */

/** @type {string[]} */
export const SEARCH_PANEL_PUBLISHED = ["_reloadSections", "_initSearchPanel"];

/** @type {string[]} */
export const SEARCH_PANEL_REQUIRES = [
    "_getCategoryDomain",
    "_getDomain",
    "_getFilterDomain",
    "_getGroupDomain",
    "_notify",
    "_withNotificationsBlockedAsync",
    "categories",
    "filters",
];

/** @type {string[]} */
export const SEARCH_PANEL_SHARED_STATE = [
    "_reloadMutex",
    "_sectionLoadIds",
    "_sections",
    "display",
    "globalContext",
    "orm",
    "resModel",
    "searchDomain",
    "searchPanelInfo",
    "sections",
    "sectionsPromise",
];

/** @type {string[]} */
export const SEARCH_PROPERTIES_PUBLISHED = ["updateSearchViewItemsProperty"];

/** @type {string[]} */
export const SEARCH_PROPERTIES_REQUIRES = ["_notify", "getSearchItems"];

/** @type {string[]} */
export const SEARCH_PROPERTIES_SHARED_STATE = [
    "_enrichedSearchItems",
    "_filledPropertyFields",
    "fieldService",
    "globalContext",
    "nextGroupId",
    "nextId",
    "query",
    "resModel",
    "searchItems",
    "searchViewFields",
];

/** @type {string[]} */
export const SEARCH_FAVORITES_PUBLISHED = [
    "_createGroupOfFavorites",
    "_reconciliateFavorites",
];

/** @type {string[]} */
export const SEARCH_FAVORITES_REQUIRES = [
    "_createGroupOfSearchItems",
    "_getContext",
    "_getDomain",
    "_getGroupBy",
    "_getOrderBy",
    "_notify",
    "_withNotificationsBlocked",
    "clearQuery",
];

/** @type {string[]} */
export const SEARCH_FAVORITES_SHARED_STATE = [
    "_enrichedSearchItems",
    "env",
    "globalContext",
    "irFilters",
    "nextGroupId",
    "nextId",
    "orm",
    "query",
    "resModel",
    "searchItems",
    "searchViewFields",
];

/** @type {string[]} */
export const SEARCH_SPLIT_DOMAIN_PUBLISHED = [];

/** @type {string[]} */
export const SEARCH_SPLIT_DOMAIN_REQUIRES = [
    "_getGroupBy",
    "_getGroups",
    "_getSearchItemContext",
    "_getSearchItemGroupBys",
    "_notify",
    "_withNotificationsBlocked",
    "createNewFilters",
    "createNewGroupBy",
    "deactivateGroup",
    "domainEvalContext",
    "updateSearchViewItemsProperty",
    "isDebugMode",
];

/** @type {string[]} */
export const SEARCH_SPLIT_DOMAIN_SHARED_STATE = [
    "DomainSelectorDialog",
    "defaultGroupBy",
    "dialog",
    "env",
    "getDefaultDomain",
    "query",
    "resModel",
    "searchItems",
    "searchViewFields",
    "treeProcessor",
];

/** @type {string[]} */
export const SEARCH_QUERY_PUBLISHED = [
    "_activateDefaultSearchItems",
    "addAutoCompletionValues",
    "clearQuery",
    "createNewFilters",
    "createNewGroupBy",
    "deactivateGroup",
    "toggleDateFilter",
    "toggleDateGroupBy",
    "toggleSearchItem",
];

/** @type {string[]} */
export const SEARCH_QUERY_REQUIRES = [
    "_getSelectedGeneratorIds",
    "_notify",
    "_withNotificationsBlocked",
];

/** @type {string[]} */
export const SEARCH_QUERY_SHARED_STATE = [
    "defaultGroupBy",
    "defaultGroupByRemoved",
    "globalGroupBy",
    "nextGroupId",
    "nextGroupNumber",
    "nextId",
    "orderByCount",
    "query",
    "referenceMoment",
    "searchItems",
    "searchViewFields",
];

/** @type {string[]} */
export const SEARCH_MODEL_PUBLISHED = [
    "_createGroupOfSearchItems",
    "_getCategoryDomain",
    "_getContext",
    "_getDomain",
    "_getFilterDomain",
    "_getGroupBy",
    "_getGroupDomain",
    "_getGroups",
    "_getOrderBy",
    "_getSearchItemContext",
    "_getSearchItemGroupBys",
    "_getSelectedGeneratorIds",
    "_notify",
    "_withNotificationsBlocked",
    "_withNotificationsBlockedAsync",
    "categories",
    "domainEvalContext",
    "filters",
    "getSearchItems",
    "isDebugMode",
];

/** @type {string[]} */
export const SEARCH_MODEL_REQUIRES = [
    "_activateDefaultSearchItems",
    "_createGroupOfFavorites",
    "_reconciliateFavorites",
    "_reloadSections",
    "_initSearchPanel",
];

/** @type {string[]} */
export const SEARCH_MODEL_SHARED_STATE = [
    "DomainSelectorDialog",
    "_context",
    "_domain",
    "_enrichedSearchItems",
    "_facets",
    "_filledPropertyFields",
    "_groupBy",
    "_orderBy",
    "_pendingNotification",
    "_reloadMutex",
    "_sectionLoadIds",
    "_sections",
    "_sectionsByType",
    "canOrderByCount",
    "defaultGroupByRemoved",
    "dialog",
    "fieldService",
    "getDefaultDomain",
    "globalContext",
    "hideCustomGroupBy",
    "intervalOptions",
    "irFilters",
    "nextGroupId",
    "nextGroupNumber",
    "nextId",
    "orderByCount",
    "orm",
    "query",
    "referenceMoment",
    "searchMenuTypes",
    "searchPanelInfo",
    "searchViewArch",
    "sections",
    "treeProcessor",
    "viewService",
];

/** @type {Record<string, string>} */
export const SEARCH_COMPOSITION_IDENTITY = {
    "search/search_panel/search_panel_mixin.js": "toggleCategoryValue",
    "search/search_properties_mixin.js": "updateSearchViewItemsProperty",
    "search/search_favorites_mixin.js": "createNewFavorite",
    "search/search_split_domain_mixin.js": "splitAndAddDomain",
    "search/search_query_mixin.js": "toggleSearchItem",
    "search/search_model.js": "load",
};

/** @type {string[]} */
export const SEARCH_COMPOSITION_CONDITIONAL_STATE = [
    "irFilters",
    "searchDomain",
    "sectionsPromise",
];

/** @type {string[]} */
export const SEARCH_COMPOSITION_BASE_SURFACE = ["trigger"];

/** @type {string[]} */
export const SEARCH_COMPOSITION_ORDER = [
    "search/search_panel/search_panel_mixin.js",
    "search/search_properties_mixin.js",
    "search/search_favorites_mixin.js",
    "search/search_split_domain_mixin.js",
    "search/search_query_mixin.js",
    "search/search_model.js",
];

/** @typedef {{ */

/** @type {Record<string, UnitContract>} */
export const SEARCH_COMPOSITION_CONTRACT = {
    "search/search_panel/search_panel_mixin.js": {
        published: SEARCH_PANEL_PUBLISHED,
        requires: SEARCH_PANEL_REQUIRES,
        sharedState: SEARCH_PANEL_SHARED_STATE,
    },
    "search/search_properties_mixin.js": {
        published: SEARCH_PROPERTIES_PUBLISHED,
        requires: SEARCH_PROPERTIES_REQUIRES,
        sharedState: SEARCH_PROPERTIES_SHARED_STATE,
    },
    "search/search_favorites_mixin.js": {
        published: SEARCH_FAVORITES_PUBLISHED,
        requires: SEARCH_FAVORITES_REQUIRES,
        sharedState: SEARCH_FAVORITES_SHARED_STATE,
    },
    "search/search_split_domain_mixin.js": {
        published: SEARCH_SPLIT_DOMAIN_PUBLISHED,
        requires: SEARCH_SPLIT_DOMAIN_REQUIRES,
        sharedState: SEARCH_SPLIT_DOMAIN_SHARED_STATE,
    },
    "search/search_query_mixin.js": {
        published: SEARCH_QUERY_PUBLISHED,
        requires: SEARCH_QUERY_REQUIRES,
        sharedState: SEARCH_QUERY_SHARED_STATE,
    },
    "search/search_model.js": {
        published: SEARCH_MODEL_PUBLISHED,
        requires: SEARCH_MODEL_REQUIRES,
        sharedState: SEARCH_MODEL_SHARED_STATE,
    },
};
