// @ts-check
/** @odoo-module native */

/**
 * The interface of the `SearchModel` mixin composition, declared.
 *
 * `SearchModel` is composed from five mixin factories that collaborate through
 * `this`. A `this._notify()` in a mixin produces no import edge, so the
 * composition's real interface -- which unit may call what on which other --
 * was carried by nothing: `js_private_access` reports **zero** accesses in
 * `search/` not because there are none but because a mixin merges into its host
 * and leaves no cross-module member access to detect.
 *
 * This file is to the composition what `static_list_contract.js` is to
 * `model/relational_model/`: the declaration that makes the coupling
 * enumerable, reviewable and testable. It is measured, not aspirational --
 * `js_mixin_coupling.py --check` fails when a unit reaches for something it
 * does not declare here, and `search_composition_contract.test.js` fails when a
 * declaration names something the runtime does not have.
 *
 * THREE KINDS OF REACH, AND WHY THEY ARE SEPARATE
 * -----------------------------------------------
 *
 * - `_PUBLISHED` -- what the rest of the composition may call on this unit.
 *   Its siblings' `_REQUIRES` must be covered by some unit's `_PUBLISHED`.
 * - `_REQUIRES` -- the sibling operations this unit calls. This is the number
 *   to drive down: every entry is a unit that cannot be read, tested or moved
 *   on its own.
 * - `_SHARED_STATE` -- host instance state this unit reads or writes. These
 *   names are declared by no class body at all: they are assigned in
 *   `SearchModel.setup()` and reached by `this.searchItems`, `this.query`,
 *   `this.nextId` from anywhere in the chain. They are the JavaScript analogue
 *   of the `unowned` bucket `js_private_access` reports apart from its count --
 *   arguably worse than a declared private, because there is no declaration to
 *   remove and no owner to attribute to. Counting them here is the first time
 *   they have been written down.
 *
 * WHAT THE SHAPE OF THIS FILE SAYS
 * --------------------------------
 *
 * `SEARCH_MODEL_REQUIRES` is the entry that should not exist. It is the host
 * reaching *down* into its own mixins -- `_loadFromArch` calling
 * `_createGroupOfFavorites`, `_notify` calling `_reloadSections` -- and it is
 * what holds the six units in one strongly-connected component: the mixins
 * reach up for shared state, the host reaches down for behaviour, and every
 * pair is a cycle. A mixin that only reached up would be a layer.
 *
 * `SEARCH_MODEL_SHARED_STATE` is the second finding: 51 names, none declared
 * as a class field, every one of them assigned in one method and read from
 * five files.
 */

// ---------------------------------------------------------------------------
// search/search_panel/search_panel_mixin.js
// ---------------------------------------------------------------------------

/**
 * What the rest of the composition may call on this unit.
 * @type {string[]}
 */
export const SEARCH_PANEL_PUBLISHED = [
    "_fetchSections",
    "_reloadSections",
    "_shouldWaitForData",
];

/**
 * Sibling operations this unit calls. Each one is a reason it cannot be
 * read or tested on its own.
 * @type {string[]}
 */
export const SEARCH_PANEL_REQUIRES = [
    "_getCategoryDomain",
    "_getDomain",
    "_getFilterDomain",
    "_getGroupDomain",
    "_notify",
    "categories",
    "filters",
];

/**
 * Host instance state this unit reads or writes.
 * @type {string[]}
 */
export const SEARCH_PANEL_SHARED_STATE = [
    "_reloadMutex",
    "_sectionLoadIds",
    "_sections",
    "blockNotification",
    "display",
    "globalContext",
    "orm",
    "resModel",
    "searchDomain",
    "searchPanelInfo",
    "sections",
    "sectionsPromise",
];

// ---------------------------------------------------------------------------
// search/search_properties_mixin.js
// ---------------------------------------------------------------------------

/**
 * What the rest of the composition may call on this unit.
 * @type {string[]}
 */
export const SEARCH_PROPERTIES_PUBLISHED = ["fillSearchViewItemsProperty"];

/**
 * Sibling operations this unit calls. Each one is a reason it cannot be
 * read or tested on its own.
 * @type {string[]}
 */
export const SEARCH_PROPERTIES_REQUIRES = ["_notify", "_rawContext", "getSearchItems"];

/**
 * Host instance state this unit reads or writes.
 * @type {string[]}
 */
export const SEARCH_PROPERTIES_SHARED_STATE = [
    "_enrichedSearchItems",
    "_filledPropertyFields",
    "fieldService",
    "nextGroupId",
    "nextId",
    "query",
    "resModel",
    "searchItems",
    "searchViewFields",
];

// ---------------------------------------------------------------------------
// search/search_favorites_mixin.js
// ---------------------------------------------------------------------------

/**
 * What the rest of the composition may call on this unit.
 * @type {string[]}
 */
export const SEARCH_FAVORITES_PUBLISHED = [
    "_createGroupOfFavorites",
    "_reconciliateFavorites",
];

/**
 * Sibling operations this unit calls. Each one is a reason it cannot be
 * read or tested on its own.
 * @type {string[]}
 */
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

/**
 * Host instance state this unit reads or writes.
 * @type {string[]}
 */
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

// ---------------------------------------------------------------------------
// search/search_split_domain_mixin.js
// ---------------------------------------------------------------------------

/**
 * What the rest of the composition may call on this unit.
 * @type {string[]}
 */
export const SEARCH_SPLIT_DOMAIN_PUBLISHED = ["splitAndAddDomain"];

/**
 * Sibling operations this unit calls. Each one is a reason it cannot be
 * read or tested on its own.
 * @type {string[]}
 */
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
    "fillSearchViewItemsProperty",
    "isDebugMode",
];

/**
 * Host instance state this unit reads or writes.
 * @type {string[]}
 */
export const SEARCH_SPLIT_DOMAIN_SHARED_STATE = [
    "defaultGroupBy",
    "env",
    "query",
    "resModel",
    "searchItems",
    "treeProcessor",
];

// ---------------------------------------------------------------------------
// search/search_query_mixin.js
// ---------------------------------------------------------------------------

/**
 * What the rest of the composition may call on this unit.
 * @type {string[]}
 */
export const SEARCH_QUERY_PUBLISHED = [
    "_withNotificationsBlocked",
    "addAutoCompletionValues",
    "clearQuery",
    "createNewFilters",
    "createNewGroupBy",
    "deactivateGroup",
    "toggleDateFilter",
    "toggleDateGroupBy",
    "toggleSearchItem",
];

/**
 * Sibling operations this unit calls. Each one is a reason it cannot be
 * read or tested on its own.
 * @type {string[]}
 */
export const SEARCH_QUERY_REQUIRES = [
    "_getSelectedGeneratorIds",
    "_notify",
    "isDebugMode",
    "splitAndAddDomain",
];

/**
 * Host instance state this unit reads or writes.
 * @type {string[]}
 */
export const SEARCH_QUERY_SHARED_STATE = [
    "DomainSelectorDialog",
    "blockNotification",
    "defaultGroupBy",
    "defaultGroupByRemoved",
    "dialog",
    "getDefaultDomain",
    "globalContext",
    "globalGroupBy",
    "nextGroupId",
    "nextGroupNumber",
    "nextId",
    "orderByCount",
    "query",
    "referenceMoment",
    "resModel",
    "searchItems",
    "searchViewFields",
];

// ---------------------------------------------------------------------------
// search/search_model.js
// ---------------------------------------------------------------------------

/**
 * What the mixins call on the host: the derivation family (`_getDomain`,
 * `_getContext`, `_getGroupBy` ...), the item registry, and the notification
 * channel every mutation ends with.
 * @type {string[]}
 */
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
    "_rawContext",
    "categories",
    "filters",
    "getSearchItems",
    "isDebugMode",
];

/**
 * The host reaching down into its mixins. **This list is the cycle.** Every
 * entry is a lifecycle step `SearchModel` performs by naming a method one of
 * its own mixins owns, which is what makes the composition mutually recursive
 * rather than layered. Drive it to zero.
 * @type {string[]}
 */
export const SEARCH_MODEL_REQUIRES = [
    "_createGroupOfFavorites",
    "_fetchSections",
    "_reconciliateFavorites",
    "_reloadSections",
    "_shouldWaitForData",
    "addAutoCompletionValues",
    "toggleDateFilter",
    "toggleDateGroupBy",
    "toggleSearchItem",
];

/**
 * Instance state assigned in `setup()` / `_loadFromArch` and reached from
 * across the chain. Declared by no class body, so no gate but this one can
 * see it.
 * @type {string[]}
 */
export const SEARCH_MODEL_SHARED_STATE = [
    "DomainSelectorDialog",
    "_context",
    "_domain",
    "_enrichedSearchItems",
    "_facets",
    "_filledPropertyFields",
    "_groupBy",
    "_groups",
    "_orderBy",
    "_pendingNotification",
    "_reloadMutex",
    "_sectionLoadIds",
    "_sections",
    "_sectionsByType",
    "_sectionsByTypeSource",
    "blockNotification",
    "canOrderByCount",
    "defaultGroupBy",
    "defaultGroupByRemoved",
    "dialog",
    "display",
    "env",
    "fieldService",
    "getDefaultDomain",
    "globalContext",
    "globalDomain",
    "globalGroupBy",
    "globalOrderBy",
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
    "resModel",
    "searchDomain",
    "searchItems",
    "searchMenuTypes",
    "searchPanelInfo",
    "searchViewArch",
    "searchViewFields",
    "searchViewId",
    "sections",
    "sectionsPromise",
    "treeProcessor",
    "viewService",
];

/**
 * Shared state that a loaded `SearchModel` does not necessarily carry.
 *
 * The other 102 `_SHARED_STATE` names exist on every model the moment it has
 * loaded, and `search_composition_contract.test.js` asserts that against a real
 * one. These three do not, because nothing assigns them on the path a model
 * without a search panel takes:
 *
 *   irFilters        `_resolveSearchView` assigns it only when the search view
 *                    ships `ir.filters`; `_loadFromArch` reads it as
 *                    `this.irFilters || []`, which is the guard for its absence.
 *   searchDomain     assigned by `_seedSearchPanel` and `_reloadSections`, both
 *                    search-panel paths.
 *   sectionsPromise  same two, and for the same reason.
 *
 * Listing them is the point rather than an exemption: the conformance test
 * asserts they are absent from a panel-less model, so a name that starts being
 * assigned unconditionally fails here until it moves out of this list.
 *
 * @type {string[]}
 */
export const SEARCH_COMPOSITION_CONDITIONAL_STATE = [
    "irFilters",
    "searchDomain",
    "sectionsPromise",
];

/**
 * What the composition inherits from the class the chain is applied to.
 *
 * `SearchPanelMixin` is applied to owl's `EventBus`, so `trigger` resolves on
 * every unit without any of them declaring it. It is separated from
 * `_SHARED_STATE` because it is not shared state: it is a method of the base,
 * it has an owner, and the owner is not ours. Folding it in would have made
 * the shared-state count one larger and one less true.
 *
 * @type {string[]}
 */
export const SEARCH_COMPOSITION_BASE_SURFACE = ["trigger"];

/**
 * The composition, innermost first: `SearchPanelMixin` is applied to `EventBus`
 * and `SearchModel` is the most-derived class. The order is load-bearing --
 * `super` resolves inward along it, and it decides which unit's override of a
 * shared name wins.
 *
 * @type {string[]}
 */
export const SEARCH_COMPOSITION_ORDER = [
    "search/search_panel/search_panel_mixin.js",
    "search/search_properties_mixin.js",
    "search/search_favorites_mixin.js",
    "search/search_split_domain_mixin.js",
    "search/search_query_mixin.js",
    "search/search_model.js",
];

/**
 * One unit's three declarations.
 *
 * @typedef {{
 * published: string[],
 * requires: string[],
 * sharedState: string[],
 * }} UnitContract
 */

/**
 * Every declaration above, keyed by module, for the conformance test and for
 * `js_mixin_coupling.py --check`.
 *
 * Typed as a `Record` rather than left to inference: the keys are module paths
 * that callers index with a `string` taken from `SEARCH_COMPOSITION_ORDER`, and
 * an inferred literal type makes every one of those lookups an implicit `any`
 * under `noImplicitAny`.
 *
 * @type {Record<string, UnitContract>}
 */
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
