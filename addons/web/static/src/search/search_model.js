// @ts-check
/** @odoo-module native */

/** @module @web/search/search_model - Search state machine managing facets, domains, groupbys, and favorites */

import { EventBus, toRaw } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { SearchModelEvent } from "@web/core/events";
import { DateTime } from "@web/core/l10n/luxon";
import { evaluateExpr } from "@web/core/py_js/py";
import { deepCopy } from "@web/core/utils/collections/objects";
import { user } from "@web/services/user";

import { SearchArchParser } from "./search_arch_parser.js";
import { computeSearchContext, computeSearchItemContext } from "./search_context.js";
import {
    computeCategoryDomain,
    computeDateFilterDomain,
    computeDomain,
    computeFieldDomain,
    computeFilterDomain,
    computeGroupDomain,
    computeSearchItemDomain,
    computeSearchPanelDomain,
} from "./search_domain.js";
import { enrichSearchItem } from "./search_enrichment.js";
import { buildFacets } from "./search_facets.js";
import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "./search_favorites.js";
import {
    computeGroupBy,
    computeOrderBy,
    computeSearchItemGroupBys,
    getQueryGroups,
    getSelectedGeneratorIds,
} from "./search_group_by.js";
import * as panelState from "./search_panel/search_panel_state.js";
import {
    fetchPropertiesDefinition as _fetchPropertiesDefinition,
    fillSearchViewItemsProperty as _fillSearchViewItemsProperty,
    getSearchItemsProperties as _getSearchItemsProperties,
} from "./search_properties.js";
import * as queryMut from "./search_query_mutations.js";
import { splitAndAddDomain as _splitAndAddDomain } from "./search_split_domain.js";
import {
    arrayToMap,
    execute,
    extractSearchDefaults,
    mapToArray,
} from "./search_state.js";
import { getIntervalOptions } from "./utils/dates.js";

/** @import { Context } from "@web/core/context" */
/** @import { Domain, DomainListRepr } from "@web/core/domain" */
/** @import { OrderTerm } from "@web/core/utils/order_by" */
/** @import { Field, FieldInfo, SearchParams } from "@web/model/types" */

/**
 * Structural contract between SearchModel and its delegate modules
 * (search_query_mutations, search_split_domain, search_properties,
 * search_panel/search_panel_state). It documents the instance state those
 * delegates read or write — the real seam left by the facade split — so a
 * rename on the model side is caught at the seam instead of type-checking
 * silently. Delegates also call back into model methods (`_notify`,
 * `_getGroups`, `createNewFilters`, …); those, plus subclass extensions
 * (documents, knowledge, account_reports, …), are admitted by the
 * `Record<string, any>` intersection.
 *
 * @typedef {{
 *   env: Object,
 *   orm: Object,
 *   dialog: Object,
 *   DomainSelectorDialog: Function,
 *   getDefaultDomain: Function,
 *   treeProcessor: Object,
 *   resModel: string,
 *   isDebugMode: boolean,
 *   globalContext: Object,
 *   referenceMoment: Object,
 *   blockNotification: boolean,
 *   orderByCount: string | false,
 *   defaultGroupBy: string[] | undefined,
 *   query: Object[],
 *   searchItems: Record<number, Object>,
 *   searchViewFields: Record<string, Object>,
 *   nextId: number,
 *   nextGroupId: number,
 *   nextGroupNumber: number,
 *   facets: Object[],
 *   sections: Map<number, Section>,
 *   categories: Object[],
 *   filters: Object[],
 *   searchDomain: any[],
 *   searchPanelInfo: Object,
 *   sectionsPromise: Promise<void> | undefined,
 *   categoriesLoadId: number,
 *   filtersLoadId: number,
 *   display: Object,
 *   _sections: Object[] | null,
 * } & Record<string, any>} SearchModelLike
 */

/**
 * @typedef {Object} Section
 * @property {number} id
 * @property {string} type
 * @property {Map<any, Object>} values
 * @property {Map<any, Object>} [groups]
 * @property {string} [errorMsg]
 * @property {string} [fieldName]
 * @property {string} [description]
 * @property {boolean} [enableCounters]
 * @property {number} [limit]
 * @property {string} [icon]
 * @property {string} [color]
 * @property {boolean} [expand]
 * @property {string|false} [hierarchize]
 * @property {any} [activeValueId]
 * @property {string} [domain]
 * @property {string|false} [groupBy]
 */
/** @typedef {Section & { type: "category" }} Category */
/** @typedef {Section & { type: "filter" }} Filter */
/** @typedef {(section: Section) => boolean} SectionPredicate */

export class SearchModel extends EventBus {
    constructor(env, services, args) {
        super();
        this.env = env;
        this.setup(services, args);
    }

    setup(services, _args) {
        // services
        const {
            field: fieldService,
            orm,
            view,
            dialog,
            treeProcessor,
            DomainSelectorDialog,
            getDefaultDomain,
        } = services;
        this.orm = orm;
        this.fieldService = fieldService;
        this.viewService = view;
        this.treeProcessor = treeProcessor;
        this.dialog = dialog;
        this.DomainSelectorDialog = DomainSelectorDialog;
        this.getDefaultDomain = getDefaultDomain;
        /** @type {string|false} */
        this.orderByCount = false;

        // used to manage search items related to date/datetime fields
        this.referenceMoment = DateTime.local();
        this.intervalOptions = getIntervalOptions();
        this.categoriesLoadId = 0;
        this.filtersLoadId = 0;
    }

    /**
     * @param {Object} config
     * @param {string} config.resModel
     *
     * @param {string} [config.searchViewArch="<search/>"]
     * @param {Object} [config.searchViewFields={}]
     * @param {number|false} [config.searchViewId=false]
     * @param {Object[]} [config.irFilters=[]]
     *
     * @param {boolean} [config.activateFavorite=true]
     * @param {Object} [config.context={}]
     * @param {Array} [config.domain=[]]
     * @param {Array} [config.dynamicFilters=[]]
     * @param {string[]} [config.groupBy=[]]
     * @param {boolean} [config.loadIrFilters=false]
     * @param {Object} [config.display]
     * @param {boolean} [config.display.searchPanel=true]
     * @param {OrderTerm[]} [config.orderBy=[]]
     * @param {string[]} [config.searchMenuTypes=["filter", "groupBy", "favorite"]]
     * @param {Object} [config.state]
     * @param {boolean} [config.hideCustomGroupBy]
     * @param {boolean} [config.canOrderByCount]
     * @param {string[]} [config.defaultGroupBy]
     */
    async load(config) {
        const { resModel } = config;
        if (!resModel) {
            throw Error(`SearchModel config should have a "resModel" key`);
        }
        this.resModel = resModel;

        // used to avoid useless recomputations
        this._reset();

        const { context, domain, groupBy, hideCustomGroupBy, orderBy } = config;

        this.globalContext = toRaw({ ...context });
        this.globalDomain = domain || [];
        this.globalGroupBy = groupBy || [];
        this.globalOrderBy = orderBy || [];
        this.hideCustomGroupBy = hideCustomGroupBy;

        this.searchMenuTypes = new Set(
            config.searchMenuTypes || ["filter", "groupBy", "favorite"],
        );
        this.canOrderByCount = config.canOrderByCount;
        this.defaultGroupBy = config.defaultGroupBy;

        const { irFilters, loadIrFilters, searchViewArch, searchViewId } = config;
        let { searchViewFields } = config;
        const loadSearchView =
            searchViewId !== undefined &&
            (!searchViewArch || !searchViewFields || (!irFilters && loadIrFilters));

        const searchViewDescription = {};
        if (loadSearchView) {
            const result = await this.viewService.loadViews(
                {
                    context: this.globalContext,
                    resModel,
                    views: [[searchViewId, "search"]],
                },
                {
                    actionId: this.env.config.actionId,
                    embeddedActionId: this.env.config.currentEmbeddedActionId,
                    loadIrFilters: loadIrFilters || false,
                },
            );
            Object.assign(searchViewDescription, result.views.search);
            searchViewFields = searchViewFields || result.fields;
        }
        if (searchViewArch) {
            searchViewDescription.arch = searchViewArch;
        }
        if (irFilters) {
            searchViewDescription.irFilters = irFilters;
        }
        if (searchViewId !== undefined) {
            searchViewDescription.viewId = searchViewId;
        }
        this.searchViewArch = searchViewDescription.arch || "<search/>";
        this.searchViewFields = searchViewFields || {};
        if (searchViewDescription.irFilters) {
            this.irFilters = searchViewDescription.irFilters;
        }
        if (searchViewDescription.viewId !== undefined) {
            this.searchViewId = searchViewDescription.viewId;
        }

        const { searchDefaults, searchPanelDefaults } =
            this._extractSearchDefaultsFromGlobalContext();

        if (config.state) {
            this._importState(config.state);
            this.__legacyParseSearchPanelArchAnyway(
                searchViewDescription,
                searchViewFields,
            );
            this.display = this._getDisplay(config.display);
            this._reconciliateFavorites();
            if (!this.searchPanelInfo.loaded) {
                return this._reloadSections();
            }
            return;
        }

        // try/finally: a throw between here and the end of load() (label
        // callbacks, section fetches) must not leave the model permanently
        // muted.
        this.blockNotification = true;
        try {
            this.searchItems = {};
            this.query = [];

            this.nextId = 1;
            this.nextGroupId = 1;
            this.nextGroupNumber = 1;

            const parser = new SearchArchParser(
                searchViewDescription,
                searchViewFields,
                searchDefaults,
                searchPanelDefaults,
            );
            const { labels, preSearchItems, searchPanelInfo, sections } =
                parser.parse();

            this.searchPanelInfo = {
                ...searchPanelInfo,
                loaded: false,
                shouldReload: false,
            };

            await Promise.all(labels.map((cb) => cb(this.orm)));

            // prepare search items (populate this.searchItems)
            for (const preGroup of preSearchItems || []) {
                this._createGroupOfSearchItems(preGroup);
            }
            this.nextGroupNumber =
                1 +
                Math.max(
                    ...Object.values(this.searchItems).map((i) => i.groupNumber || 0),
                    0,
                );

            const { dynamicFilters } = config;
            if (dynamicFilters) {
                this._createGroupOfDynamicFilters(dynamicFilters);
            }

            const defaultFavoriteId = this._createGroupOfFavorites(
                this.irFilters || [],
            );
            const activateFavorite =
                "activateFavorite" in config ? config.activateFavorite : true;

            // activate default search items (populate this.query)
            this._activateDefaultSearchItems(
                activateFavorite ? defaultFavoriteId : null,
            );

            // prepare search panel sections

            /** @type Map<number,Section> */
            // sections from the parser is an entries-compatible array; the
            // typedef hasn't tracked that, so cast at the boundary.
            this.sections = new Map(
                /** @type {[number, Section][]} */ (sections || []),
            );
            this.display = this._getDisplay(config.display);

            if (this.display.searchPanel) {
                /** @type {DomainListRepr} */
                this.searchDomain = /** @type {DomainListRepr} */ (
                    this._getDomain({ withSearchPanel: false })
                );
                this.sectionsPromise = (async () => {
                    await this._fetchSections(this.categories, this.filters);
                    for (const { fieldName, values } of this.filters) {
                        const filterDefaults = searchPanelDefaults[fieldName] || [];
                        for (const valueId of filterDefaults) {
                            const value = values.get(valueId);
                            if (value) {
                                value.checked = true;
                            }
                        }
                    }
                    this._sections = null;
                })();
                if (
                    Object.keys(searchPanelDefaults).length ||
                    this._shouldWaitForData(false)
                ) {
                    await this.sectionsPromise;
                }
            }
        } finally {
            this.blockNotification = false;
        }
    }

    /**
     * @param {Object} [config={}]
     * @param {Object} [config.context={}]
     * @param {Array} [config.domain=[]]
     * @param {string[]} [config.groupBy=[]]
     * @param {OrderTerm[]} [config.orderBy=[]]
     */
    async reload(config = {}) {
        this._reset();

        const { context, domain, groupBy, orderBy } = config;

        this.globalContext = toRaw({ ...context });
        this.globalDomain = domain || [];
        this.globalGroupBy = groupBy || [];
        this.globalOrderBy = orderBy || [];

        // Called for its side effect: strips the search_default_* keys out of
        // this.globalContext (their values feed the initial section state).
        this._extractSearchDefaultsFromGlobalContext();

        await this._reloadSections();
    }

    //--------------------------------------------------------------------------
    // Getters
    //--------------------------------------------------------------------------

    /**
     * @returns {Category[]}
     */
    get categories() {
        return /** @type {Category[]} */ (
            [...this.sections.values()].filter((s) => s.type === "category")
        );
    }

    /**
     * Raw memoized context for internal read-only consumers: the public
     * `context` getter deep-copies on every access.
     * @returns {Context}
     */
    get _rawContext() {
        if (!this._context) {
            this._context = makeContext([this.globalContext, this._getContext()]);
        }
        return this._context;
    }

    /**
     * @returns {Context} should be imported from context.js?
     */
    get context() {
        return deepCopy(this._rawContext);
    }

    /**
     * @returns {DomainListRepr}
     */
    get domain() {
        if (!this._domain) {
            this._domain = /** @type {DomainListRepr} */ (this._getDomain());
        }
        return deepCopy(this._domain);
    }

    /**
     * @returns {string}
     */
    get domainString() {
        return this._getDomain({ raw: true }).toString();
    }

    get domainEvalContext() {
        return { ...this.globalContext, ...user.context };
    }

    get facets() {
        // Memoised like context/domain/groupBy/orderBy: _getFacets rebuilds every
        // facet domain on each call and this is read on every render (and once
        // per facet in clearFilters). Cleared in _reset(); no consumer mutates
        // the returned array.
        if (!this._facets) {
            const facets = [];
            for (const facet of this._getFacets()) {
                if (facet.type === "groupBy" && !this.searchMenuTypes.has(facet.type)) {
                    continue;
                }
                facets.push(facet);
            }
            this._facets = facets;
        }
        return this._facets;
    }

    /**
     * @returns {Filter[]}
     */
    get filters() {
        return /** @type {Filter[]} */ (
            [...this.sections.values()].filter((s) => s.type === "filter")
        );
    }

    /**
     * @returns {string[]}
     */
    get groupBy() {
        if (!this.searchMenuTypes.has("groupBy")) {
            return [];
        }
        if (!this._groupBy) {
            this._groupBy = this._getGroupBy();
        }
        return deepCopy(this._groupBy);
    }

    /**
     * @returns {OrderTerm[]}
     */
    get orderBy() {
        if (!this._orderBy) {
            this._orderBy = this._getOrderBy();
        }
        return deepCopy(this._orderBy);
    }

    get isDebugMode() {
        return !!this.env.debug;
    }
    //--------------------------------------------------------------------------
    // Public
    //--------------------------------------------------------------------------

    /** Activate a filter of type 'field' with autocomplete value. */
    addAutoCompletionValues(searchItemId, autocompleteValue) {
        return queryMut.addAutoCompletionValues(this, searchItemId, autocompleteValue);
    }

    /** Remove all query elements. */
    clearQuery() {
        return queryMut.clearQuery(this);
    }

    /** Remove filter, field and favorite facets but keep groupBy ones. */
    clearFilters() {
        return queryMut.clearFilters(this);
    }

    /**
     * Create a new filter of type 'favorite' and activate it.
     * @param {Object} params
     * @returns {Promise<number>}
     */
    async createNewFavorite(params) {
        return queryMut.createNewFavorite(this, params);
    }

    /**
     * Create new search items of type 'filter' and activate them.
     * @param {Object[]} prefilters
     * @returns {number[]} ids of the created search items
     */
    createNewFilters(prefilters) {
        return queryMut.createNewFilters(this, prefilters);
    }

    /**
     * Create a new filter of type 'groupBy' or 'dateGroupBy' and activate it.
     * @param {string} fieldName
     * @param {Object} [param]
     * @returns {number} id of the created search item
     */
    createNewGroupBy(fieldName, { interval, invisible } = {}) {
        return queryMut.createNewGroupBy(this, fieldName, { interval, invisible });
    }

    /** Deactivate a group, i.e. delete the query elements with given groupId. */
    deactivateGroup(groupId) {
        return queryMut.deactivateGroup(this, groupId);
    }

    /** Create an ir.filters record on the server. */
    async _createIrFilters(irFilter) {
        return queryMut.createIrFilters(this, irFilter);
    }

    /**
     * @returns {Object}
     */
    exportState() {
        const state = {};
        execute(mapToArray, this, state);
        return state;
    }

    getIrFilterValues(params) {
        const { irFilter } = this._getIrFilterDescription(params);
        return irFilter;
    }

    getPreFavoriteValues(params) {
        const { preFavorite } = this._getIrFilterDescription(params);
        return preFavorite;
    }

    /**
     * Return an array containing enriched copies of all searchElements or of those
     * satifying the given predicate if any
     * @param {(searchItem: Object) => boolean} [predicate]
     * @returns {Object[]}
     */
    getSearchItems(predicate) {
        // Memoised like _groups/_facets: enriching every item is costly and
        // SearchBarMenu reads this several times per render. Cleared in
        // _reset() and whenever items are created outside a query cycle.
        if (!this._enrichedSearchItems) {
            const domainEvalContext = this.domainEvalContext;
            const enrichedSearchItems = [];
            for (const searchItem of Object.values(this.searchItems)) {
                const enrichedSearchitem = this._enrichItem(searchItem);
                if (enrichedSearchitem) {
                    const isInvisible =
                        "invisible" in searchItem &&
                        evaluateExpr(searchItem.invisible, domainEvalContext);
                    if (!isInvisible) {
                        enrichedSearchItems.push(enrichedSearchitem);
                    }
                }
            }
            this._enrichedSearchItems = enrichedSearchItems;
        }
        const searchItems = predicate
            ? this._enrichedSearchItems.filter(predicate)
            : [...this._enrichedSearchItems];
        if (searchItems.some((f) => f.type === "favorite")) {
            searchItems.sort((f1, f2) => f1.groupNumber - f2.groupNumber);
        }
        return searchItems;
    }

    /**
     * Returns a sorted list of section copies, optionally filtered.
     * @param {SectionPredicate} [predicate]
     * @returns {Section[]}
     */
    getSections(predicate) {
        return panelState.getSections(this, predicate);
    }

    search() {
        this.trigger(SearchModelEvent.UPDATE);
    }

    async splitAndAddDomain(domain, groupId) {
        return _splitAndAddDomain(this, domain, groupId);
    }

    /** Set the active value of a category. */
    toggleCategoryValue(sectionId, valueId) {
        return panelState.toggleCategoryValue(this, sectionId, valueId);
    }

    /** Toggle filter values on or off. */
    toggleFilterValues(sectionId, valueIds, forceTo = null) {
        return panelState.toggleFilterValues(this, sectionId, valueIds, forceTo);
    }

    /** Clear all values from the provided sections. */
    clearSections(sectionIds) {
        return panelState.clearSections(this, sectionIds);
    }

    /** Toggle a simple filter on or off. */
    toggleSearchItem(searchItemId) {
        return queryMut.toggleSearchItem(this, searchItemId);
    }

    /** Toggle a date filter query element. */
    toggleDateFilter(searchItemId, generatorId) {
        return queryMut.toggleDateFilter(this, searchItemId, generatorId);
    }

    /** Toggle a date groupBy interval. */
    toggleDateGroupBy(searchItemId, intervalId) {
        return queryMut.toggleDateGroupBy(this, searchItemId, intervalId);
    }

    /** Open the custom filter dialog (DomainSelectorDialog). */
    async spawnCustomFilterDialog() {
        return queryMut.spawnCustomFilterDialog(this);
    }

    /** Toggle groupBy sort direction. */
    switchGroupBySort() {
        return queryMut.switchGroupBySort(this);
    }

    /** Generate search items for properties. Delegates to search_properties.js. */
    async getSearchItemsProperties(searchItem) {
        return _getSearchItemsProperties(this, searchItem);
    }

    //--------------------------------------------------------------------------
    // Private methods
    //--------------------------------------------------------------------------

    /** Lazily populate property-based search/group-by items. Delegates to search_properties.js. */
    async fillSearchViewItemsProperty() {
        return _fillSearchViewItemsProperty(this);
    }

    /** Fetch property definitions. Delegates to search_properties.js. */
    async _fetchPropertiesDefinition(resModel, fieldName) {
        return _fetchPropertiesDefinition(this, resModel, fieldName);
    }

    /**
     * Activate the default favorite (if any) or all default filters.
     */
    _activateDefaultSearchItems(defaultFavoriteId) {
        if (defaultFavoriteId) {
            // Activate default favorite
            this.toggleSearchItem(defaultFavoriteId);
        } else {
            // Activate default filters
            Object.values(this.searchItems)
                .filter((f) => f.isDefault && f.type !== "favorite")
                .sort((f1, f2) => (f1.defaultRank || 100) - (f2.defaultRank || 100))
                .forEach((f) => {
                    if (f.type === "dateFilter") {
                        this.toggleDateFilter(f.id);
                    } else if (f.type === "dateGroupBy") {
                        this.toggleDateGroupBy(f.id);
                    } else if (f.type === "field") {
                        this.addAutoCompletionValues(f.id, f.defaultAutocompleteValue);
                    } else {
                        this.toggleSearchItem(f.id);
                    }
                });
        }
    }

    /** Build a category tree from ORM results. */
    _createCategoryTree(sectionId, result) {
        return panelState.createCategoryTree(this, sectionId, result);
    }

    /** Build a filter tree from ORM results. */
    _createFilterTree(sectionId, result) {
        return panelState.createFilterTree(this, sectionId, result);
    }

    /**
     * Add filters of type 'filter' determined by the key array dynamicFilters.
     */
    _createGroupOfDynamicFilters(dynamicFilters) {
        const pregroup = dynamicFilters.map((filter) => ({
            groupNumber: this.nextGroupNumber,
            description: filter.description,
            domain: filter.domain,
            isDefault: "is_default" in filter ? filter.is_default : true,
            type: "filter",
        }));
        this.nextGroupNumber++;
        this._createGroupOfSearchItems(pregroup);
    }

    /**
     * Add filters of type 'favorite' determined by the array this.favoriteFilters.
     */
    _createGroupOfFavorites(irFilters) {
        let defaultFavoriteId = null;
        irFilters.forEach((irFilter) => {
            const favorite = this._irFilterToFavorite(irFilter);
            this._createGroupOfSearchItems([favorite]);
            if (favorite.isDefault) {
                defaultFavoriteId = favorite.id;
            }
        });
        return defaultFavoriteId;
    }

    /**
     * Using a list (a 'pregroup') of 'prefilters', create new filters in `searchItems`
     * for each prefilter. The new filters belong to a same new group.
     */
    _createGroupOfSearchItems(pregroup) {
        pregroup.forEach((preSearchItem) => {
            const searchItem = Object.assign(preSearchItem, {
                groupId: this.nextGroupId,
                id: this.nextId,
            });
            this.searchItems[this.nextId] = searchItem;
            this.nextId++;
        });
        this.nextGroupId++;
        // New items can be created outside a query cycle (e.g. lazily loaded
        // properties): invalidate the enriched search items memo.
        this._enrichedSearchItems = null;
    }

    /**
     * Return null, or a copy of the filter enriched with info used only
     * outside the control panel model (search bar, menus). Null means the
     * filter should not appear.
     */
    _enrichItem(searchItem) {
        return enrichSearchItem(
            searchItem,
            this.query,
            this.referenceMoment,
            this.intervalOptions,
        );
    }

    /** Ensure the active category value is among existing values. */
    _ensureCategoryValue(category, valueIds) {
        return panelState.ensureCategoryValue(category, valueIds);
    }

    _extractSearchDefaultsFromGlobalContext() {
        return extractSearchDefaults(this.globalContext);
    }

    /** Fetch values for each category at startup or reload. */
    async _fetchCategories(categories) {
        return panelState.fetchCategories(this, categories);
    }

    /** Fetch values for each filter section. */
    async _fetchFilters(filters) {
        return panelState.fetchFilters(this, filters);
    }

    /** Fetch values for the given categories and filters. */
    async _fetchSections(categoriesToLoad, filtersToLoad) {
        return panelState.fetchSections(this, categoriesToLoad, filtersToLoad);
    }

    /**
     * Domain based on the current active categories; excludedCategoryId, if
     * given, is left out of the computation.
     * @param {number} [excludedCategoryId]
     * @returns {Array[]}
     */
    _getCategoryDomain(excludedCategoryId) {
        return computeCategoryDomain(
            this.categories,
            this.searchViewFields,
            excludedCategoryId,
        );
    }

    /**
     * Construct a single context from the contexts of
     * filters of type 'filter', 'favorite', and 'field'.
     * @returns {Object}
     */
    _getContext() {
        return computeSearchContext(this._getGroups(), user.context, (activeItem) =>
            this._getSearchItemContext(activeItem),
        );
    }

    /**
     * Compute the string representation or the description of the current domain associated
     * with a date filter starting from its corresponding query elements.
     */
    _getDateFilterDomain(dateFilter, generatorIds, key = "domain") {
        return computeDateFilterDomain(
            this.referenceMoment,
            dateFilter,
            generatorIds,
            key,
        );
    }

    /**
     * Which components are displayed in the current action. Components are
     * opt-out (shown unless a falsy value is given); the search panel must
     * also match the view type when instantiated in a view.
     * @private
     * @param {Object} [display={}]
     * @returns {{ controlPanel: Object | false, searchPanel: boolean }}
     */
    _getDisplay(display = {}) {
        const { viewTypes } = this.searchPanelInfo;
        const { viewType } = this.env.config;
        return {
            controlPanel: "controlPanel" in display ? display.controlPanel : {},
            searchPanel: Boolean(
                this.sections.size &&
                (!viewType || viewTypes.includes(viewType)) &&
                ("searchPanel" in display ? display.searchPanel : true),
            ),
        };
    }

    /**
     * Return a domain created by combinining appropriately (with an 'AND') the domains
     * coming from the active groups of type 'filter', 'dateFilter', 'favorite', and 'field'.
     * @param {Object} [params]
     * @param {boolean} [params.raw=false]
     * @param {boolean} [params.withSearchPanel=true]
     * @param {boolean} [params.withGlobal=true]
     * @returns {DomainListRepr | Domain} Domain instance if 'raw', else the evaluated list domain
     */
    _getDomain(params = {}) {
        const withSearchPanel =
            ("withSearchPanel" in params ? params.withSearchPanel : true) &&
            this.display.searchPanel;
        const withGlobal = "withGlobal" in params ? params.withGlobal : true;
        return computeDomain({
            groups: this._getGroups(),
            globalDomain: this.globalDomain,
            withGlobal,
            withSearchPanel,
            getSearchItemDomain: (activeItem) => this._getSearchItemDomain(activeItem),
            getSearchPanelDomain: () => this._getSearchPanelDomain(),
            domainEvalContext: this.domainEvalContext,
            raw: params.raw,
        });
    }

    _getFacets() {
        return buildFacets({
            groups: this._getGroups(),
            searchItems: this.searchItems,
            getSearchItemDomain: (activeItem) => this._getSearchItemDomain(activeItem),
            getDateFilterDomain: (searchItem, generatorIds, key) =>
                this._getDateFilterDomain(searchItem, generatorIds, key),
            orderByCount: this.orderByCount,
            globalGroupBy: this.globalGroupBy,
            defaultGroupBy: this.defaultGroupBy,
            searchViewFields: this.searchViewFields,
            viewType: this.env.config.viewType,
        });
    }

    /**
     * Return the domain resulting from the combination of the autocomplete values
     * of a search item of type 'field'.
     */
    _getFieldDomain(field, autocompleteValues) {
        return computeFieldDomain(field, autocompleteValues);
    }

    /**
     * Domain from currently checked filters: values within a group are
     * OR'd, groups are AND'd (an ungrouped filter's values form an implicit
     * group). excludedFilterId, if given, is left out of the computation.
     * @param {number} [excludedFilterId]
     * @returns {Array[]}
     */
    _getFilterDomain(excludedFilterId) {
        return computeFilterDomain(this.filters, excludedFilterId);
    }

    /**
     * Concatenation of groupBys from active 'favorite' and 'groupBy' filters:
     * favorite's groupBys first, then 'groupBy' filters in query order.
     * Falls back to globalGroupBy / defaultGroupBy if none are found.
     * @param {Object} [options={}]
     * @param {boolean} [options.fallbackOnDefault=true]
     * @returns {string[]}
     */
    _getGroupBy(options = {}) {
        const fallbackOnDefault =
            "fallbackOnDefault" in options ? options.fallbackOnDefault : true;
        return computeGroupBy({
            groups: this._getGroups(),
            globalGroupBy: this.globalGroupBy,
            defaultGroupBy: this.defaultGroupBy,
            fallbackOnDefault,
            getSearchItemGroupBys: (activeItem) =>
                this._getSearchItemGroupBys(activeItem),
        });
    }

    /**
     * Domain(s) that complement the filter domain so record counts per
     * filter value aren't skewed by other checked values in the same group.
     * @param {Filter} filter
     * @returns {Object<string, Array[]> | Array[] | null}
     */
    _getGroupDomain(filter) {
        return computeGroupDomain(filter, this.searchViewFields);
    }

    /**
     * Reconstruct the (active) groups from the query elements.
     * @returns {Object[]}
     */
    _getGroups() {
        // Memoised within a query cycle: rebuilt up to 5x per _notify from the
        // same state, and getQueryGroups is O(query x groups). Cleared in
        // _reset(); consumers treat the result as read-only.
        if (!this._groups) {
            this._groups = getQueryGroups(this.query, this.searchItems);
        }
        return this._groups;
    }

    /**
     *
     * @private
     * @param {Object} [params={}]
     * @returns {{ preFavorite: Object, irFilter: Object }}
     */
    _getIrFilterDescription(params = {}) {
        const { description, isDefault, isShared, embeddedActionId } = params;
        const fns = this.env.__getContext__.callbacks;
        const localContext = Object.assign({}, ...fns.map((fn) => fn()));
        const gs = this.env.__getOrderBy__.callbacks;
        let localOrderBy;
        if (gs.length) {
            localOrderBy = gs.flatMap((g) => g());
        }
        return buildIrFilterDescription({
            description,
            isDefault,
            isShared,
            embeddedActionId,
            localContext,
            localOrderBy,
            getContext: () => this._getContext(),
            getDomain: () => this._getDomain({ raw: true, withGlobal: false }),
            getGroupBy: () => this._getGroupBy(),
            getOrderBy: () => this._getOrderBy(),
            globalContext: this.globalContext,
            actionId: this.env.config.actionId,
            resModel: this.resModel,
        });
    }

    /**
     * @returns {OrderTerm[]}
     */
    _getOrderBy() {
        return computeOrderBy(
            this._getGroups(),
            this.searchItems,
            this._getGroupBy(),
            this.orderByCount,
            this.globalOrderBy,
        );
    }

    /**
     * Return the context of the provided (active) filter.
     */
    _getSearchItemContext(activeItem) {
        return computeSearchItemContext(activeItem, this.searchItems);
    }

    /**
     * Return the domain of the provided filter.
     */
    _getSearchItemDomain(activeItem) {
        return computeSearchItemDomain(
            activeItem,
            this.searchItems,
            this.referenceMoment,
        );
    }

    _getSearchItemGroupBys(activeItem) {
        return computeSearchItemGroupBys(activeItem, this.searchItems);
    }

    /**
     * Starting from a date filter id, returns the array of option ids currently selected
     * for the corresponding date filter.
     */
    _getSelectedGeneratorIds(dateFilterId) {
        return getSelectedGeneratorIds(this.query, dateFilterId);
    }

    /**
     * @returns {Domain}
     */
    _getSearchPanelDomain() {
        return computeSearchPanelDomain(
            this._getCategoryDomain(),
            this._getFilterDomain(),
        );
    }

    /**
     * @param {Object} state
     */
    _importState(state) {
        execute(arrayToMap, state, this);
    }

    /**
     * @param {Object} irFilter
     */
    _irFilterToFavorite(irFilter) {
        return irFilterToFavorite(irFilter);
    }

    async _notify() {
        // Reset memoized state even when notifications are blocked: the
        // query did change, so the memos are stale either way.
        this._reset();

        if (this.blockNotification) {
            return;
        }

        await this._reloadSections();

        this.trigger(SearchModelEvent.UPDATE);
    }

    /**
     * Reconciliate the search items with the ir.filters.
     * @private
     */
    _reconciliateFavorites() {
        reconciliateFavorites(
            this.searchItems,
            this.query,
            this.irFilters,
            (irFilter) => this._irFilterToFavorite(irFilter),
            (irFilters) => this._createGroupOfFavorites(irFilters),
        );
    }

    /** Reload sections when search domain changes or search panel becomes visible. */
    async _reloadSections() {
        return panelState.reloadSections(this);
    }

    _reset() {
        this._context = null;
        this._domain = null;
        this._groupBy = null;
        this._orderBy = null;
        this._groups = null;
        this._facets = null;
        this._enrichedSearchItems = null;
        this._sections = null;
    }

    /** Whether the query should wait for section data before proceeding. */
    _shouldWaitForData(searchDomainChanged) {
        return panelState.shouldWaitForData(this, searchDomainChanged);
    }

    /**
     * Legacy compatibility: the imported state of a legacy search panel model
     * extension doesn't include the arch information, i.e. the class name and
     * view types. We have to extract those if they are not given.
     * @param {Object} searchViewDescription
     * @param {Object} searchViewFields
     */
    __legacyParseSearchPanelArchAnyway(searchViewDescription, searchViewFields) {
        if (this.searchPanelInfo) {
            return;
        }

        const parser = new SearchArchParser(searchViewDescription, searchViewFields);
        const { searchPanelInfo } = parser.parse();

        this.searchPanelInfo = {
            ...searchPanelInfo,
            loaded: false,
            shouldReload: false,
        };
    }
}
