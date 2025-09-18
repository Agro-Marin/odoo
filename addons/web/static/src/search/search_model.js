// @ts-check

/** @module @web/search/search_model - Search state machine managing facets, domains, groupbys, favorites, and comparisons */

import { EventBus, toRaw } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { evaluateExpr } from "@web/core/py_js/py";
import { deepCopy } from "@web/core/utils/collections/objects";
import { user } from "@web/services/user";

import * as panelState from "./search_panel/search_panel_state";
import * as queryMut from "./search_query_mutations";
import { SearchArchParser } from "./search_arch_parser";
import { computeSearchContext, computeSearchItemContext } from "./search_context";
import {
    computeCategoryDomain,
    computeDateFilterDomain,
    computeDomain,
    computeFieldDomain,
    computeFilterDomain,
    computeGroupDomain,
    computeSearchItemDomain,
    computeSearchPanelDomain,
} from "./search_domain";
import { enrichSearchItem } from "./search_enrichment";
import { buildFacets } from "./search_facets";
import {
    buildIrFilterDescription,
    irFilterToFavorite,
    reconciliateFavorites,
} from "./search_favorites";
import {
    computeGroupBy,
    computeOrderBy,
    computeSearchItemGroupBys,
    getQueryGroups,
    getSelectedGeneratorIds,
} from "./search_group_by";
import {
    fetchPropertiesDefinition as _fetchPropertiesDefinition,
    fillSearchViewItemsProperty as _fillSearchViewItemsProperty,
    getSearchItemsProperties as _getSearchItemsProperties,
} from "./search_properties";
import { splitAndAddDomain as _splitAndAddDomain } from "./search_split_domain";
import {
    arrayToMap,
    execute,
    extractSearchDefaults,
    mapToArray,
} from "./search_state";
import { getIntervalOptions } from "./utils/dates";

/** @import { Context } from "@web/core/context" */
/** @import { DomainListRepr } from "@web/core/domain" */
/** @import { OrderTerm } from "@web/core/utils/order_by" */
/** @import { Field, FieldInfo, SearchParams } from "@web/model/types" */

const { DateTime } = luxon;

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
 * @property {number} [index]
 * @property {any} [activeValueId]
 * @property {string} [domain]
 * @property {string|false} [groupBy]
 *
 * @typedef {Section & { type: "category" }} Category
 * @typedef {Section & { type: "filter" }} Filter
 * @typedef {(section: Section) => boolean} SectionPredicate
 */

export class SearchModel extends EventBus {
    constructor(env, services, args) {
        super();
        this.env = env;
        this.setup(services, args);
    }

    setup(services, _args) {
        // services
        const { field: fieldService, orm, view, dialog, treeProcessor, DomainSelectorDialog, getDefaultDomain } =
            services;
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

        this.blockNotification = true;

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
        const { labels, preSearchItems, searchPanelInfo, sections } = parser.parse();

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

        const defaultFavoriteId = this._createGroupOfFavorites(this.irFilters || []);
        const activateFavorite =
            "activateFavorite" in config ? config.activateFavorite : true;

        // activate default search items (populate this.query)
        this._activateDefaultSearchItems(activateFavorite ? defaultFavoriteId : null);

        // prepare search panel sections

        /** @type Map<number,Section> */
        this.sections = new Map(sections || []);
        this.display = this._getDisplay(config.display);

        if (this.display.searchPanel) {
            /** @type {DomainListRepr} */
            this.searchDomain = /** @type {DomainListRepr} */ (
                this._getDomain({ withSearchPanel: false })
            );
            this.sectionsPromise = this._fetchSections(
                this.categories,
                this.filters,
            ).then(() => {
                for (const { fieldName, values } of this.filters) {
                    const filterDefaults = searchPanelDefaults[fieldName] || [];
                    for (const valueId of filterDefaults) {
                        const value = values.get(valueId);
                        if (value) {
                            value.checked = true;
                        }
                    }
                }
            });
            if (
                Object.keys(searchPanelDefaults).length ||
                this._shouldWaitForData(false)
            ) {
                await this.sectionsPromise;
            }
        }

        this.blockNotification = false;
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

        this.globalContext = { ...context };
        this.globalDomain = domain || [];
        this.globalGroupBy = groupBy || [];
        this.globalOrderBy = orderBy || [];

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
     * @returns {Context} should be imported from context.js?
     */
    get context() {
        if (!this._context) {
            this._context = makeContext([this.globalContext, this._getContext()]);
        }
        return deepCopy(this._context);
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
        const facets = [];
        for (const facet of this._getFacets()) {
            if (facet.type === "groupBy" && !this.searchMenuTypes.has(facet.type)) {
                continue;
            }
            facets.push(facet);
        }
        return facets;
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

    /** Create new search items of type 'filter' and activate them. */
    createNewFilters(prefilters) {
        return queryMut.createNewFilters(this, prefilters);
    }

    /**
     * Create a new filter of type 'groupBy' or 'dateGroupBy' and activate it.
     * @param {string} fieldName
     * @param {Object} [param]
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
     * @param {Function} [predicate]
     * @returns {Object[]}
     */
    getSearchItems(predicate) {
        const searchItems = [];
        for (const searchItem of Object.values(this.searchItems)) {
            const enrichedSearchitem = this._enrichItem(searchItem);
            if (enrichedSearchitem) {
                const isInvisible =
                    "invisible" in searchItem &&
                    evaluateExpr(searchItem.invisible, this.domainEvalContext);
                if (!isInvisible && (!predicate || predicate(enrichedSearchitem))) {
                    searchItems.push(enrichedSearchitem);
                }
            }
        }
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
        this.trigger("update");
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
    }

    /**
     * Returns null or a copy of the provided filter with additional information
     * used only outside of the control panel model, like in search bar or in the
     * various menus. The value null is returned if the filter should not appear
     * for some reason.
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
     * Computes and returns the domain based on the current active
     * categories. If "excludedCategoryId" is provided, the category with
     * that id is not taken into account in the domain computation.
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
     * Returns which components are displayed in the current action. Components
     * are opt-out, meaning that they will be displayed as long as a falsy
     * value is not provided. With the search panel, the view type must also
     * match the given (or default) search panel view types if the search model
     * is instanciated in a view (this doesn't apply for any other action type).
     * @private
     * @param {Object} [display={}]
     * @returns {{ controlPanel: Object | false, searchPanel: boolean }}
     */
    _getDisplay(display = {}) {
        const { viewTypes } = this.searchPanelInfo;
        const { viewType } = this.env.config;
        return {
            controlPanel: "controlPanel" in display ? display.controlPanel : {},
            searchPanel:
                this.sections.size &&
                (!viewType || viewTypes.includes(viewType)) &&
                ("searchPanel" in display ? display.searchPanel : true),
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
     * Computes and returns the domain based on the current checked
     * filters. The values of a single filter are combined using a simple
     * rule: checked values within a same group are combined with an "OR"
     * operator (this is expressed as single condition using a list) and
     * groups are combined with an "AND" operator (expressed by
     * concatenation of conditions).
     * If a filter has no group, its checked values are implicitely
     * considered as forming a group (and grouped using an "OR").
     * If excludedFilterId is provided, the filter with that id is not
     * taken into account in the domain computation.
     * @param {number} [excludedFilterId]
     * @returns {Array[]}
     */
    _getFilterDomain(excludedFilterId) {
        return computeFilterDomain(this.filters, excludedFilterId);
    }

    /**
     * Return the concatenation of groupBys comming from the active filters of
     * type 'favorite' and 'groupBy'.
     * The result respects the appropriate logic: the groupBys
     * coming from an active favorite (if any) come first, then come the
     * groupBys comming from the active filters of type 'groupBy' in the order
     * defined in this.query. If no groupBys are found, one tries to
     * find some groupBys in this.globalGroupBy or this.defaultGroupBy.
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
     * Returns a domain or an object of domains used to complement
     * the filter domains to accurately describe the constrains on
     * records when computing record counts associated to the filter
     * values (if a groupBy is provided). The idea is that the checked
     * values within a group should not impact the counts for the other
     * values in the same group.
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
        return getQueryGroups(this.query, this.searchItems);
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
            this.groupBy,
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
        if (this.blockNotification) {
            return;
        }

        this._reset();

        await this._reloadSections();

        this.trigger("update");
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
