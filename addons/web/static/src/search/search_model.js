// @ts-check
/** @odoo-module native */

/** @module @web/search/search_model - Search state machine managing facets, domains, groupbys, and favorites */

import { EventBus, toRaw } from "@odoo/owl";
import { makeContext } from "@web/core/context";
import { SearchModelEvent } from "@web/core/events";
import { DateTime } from "@web/core/l10n/luxon";
import { evaluateExpr } from "@web/core/py_js/py";
import { Mutex } from "@web/core/utils/concurrency";
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
import { SearchFavoritesMixin } from "./search_favorites_mixin.js";
import {
    computeGroupBy,
    computeOrderBy,
    computeSearchItemGroupBys,
    getQueryGroups,
    getSelectedGeneratorIds,
} from "./search_group_by.js";
import { SearchPanelMixin } from "./search_panel/search_panel_mixin.js";
import { SearchPropertiesMixin } from "./search_properties_mixin.js";
import { SearchQueryMixin } from "./search_query_mixin.js";
import { SearchSplitDomainMixin } from "./search_split_domain_mixin.js";
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
 * Documents SearchModel's internal member surface — the instance state and
 * methods the split-out concerns (now the panel/properties/favorites/query/
 * split-domain mixins) read, write, or call back into. Every concern is folded
 * into the prototype chain and accesses this surface via ``this.*``; keeping the
 * surface enumerated here means a rename on the model side is a visible diff
 * against a single contract rather than a silent break scattered across mixins.
 * (Formerly the pass-`this` "delegate module" seam; the modules became mixins,
 * but the enumerated surface is still the useful invariant.)
 *
 * The former `& Record<string, any>` escape hatch (which admitted any property
 * access and defeated the whole point) has been removed.
 * Externally-provided objects (`env`, ORM/services, tree processor) are
 * intentionally `any` — they are not part of the invariant this contract guards.
 * Mutations are still funneled by convention rather than through dedicated
 * helper methods (see A11 note): tightening the typedef was the low-risk half.
 *
 * @typedef {{
 *   env: any,
 *   orm: any,
 *   dialog: any,
 *   fieldService: any,
 *   treeProcessor: any,
 *   DomainSelectorDialog: Function,
 *   getDefaultDomain: Function,
 *   resModel: string,
 *   isDebugMode: boolean,
 *   globalContext: Object,
 *   referenceMoment: Object,
 *   blockNotification: boolean,
 *   orderByCount: string | false,
 *   defaultGroupBy: string[] | undefined,
 *   defaultGroupByRemoved: boolean | undefined,
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
 *   _rawContext: Object,
 *   _sections: Object[] | null,
 *   _sectionLoadIds: Map<number, number>,
 *   _enrichedSearchItems: Object[] | null,
 *   _filledPropertyFields: any,
 *   trigger: Function,
 *   _pendingNotification: boolean | undefined,
 *   _notify: () => Promise<void>,
 *   _drainPendingNotification: () => Promise<void>,
 *   _reset: () => void,
 *   _reloadSections: () => Promise<void>,
 *   clearQuery: Function,
 *   deactivateGroup: Function,
 *   createNewFilters: Function,
 *   createNewGroupBy: Function,
 *   toggleSearchItem: Function,
 *   toggleDateGroupBy: Function,
 *   _withNotificationsBlocked: (fn: () => void) => void,
 *   splitAndAddDomain: Function,
 *   getSearchItems: Function,
 *   _createGroupOfSearchItems: Function,
 *   _createIrFilters: Function,
 *   _createCategoryTree: Function,
 *   _createFilterTree: Function,
 *   _ensureCategoryValue: Function,
 *   _fetchCategories: Function,
 *   _fetchFilters: Function,
 *   _fetchSections: Function,
 *   _fetchPropertiesDefinition: Function,
 *   _getCategoryDomain: Function,
 *   _getDomain: Function,
 *   _getFilterDomain: Function,
 *   _getGroupBy: Function,
 *   _getGroupDomain: Function,
 *   _getGroups: Function,
 *   _getIrFilterDescription: Function,
 *   _getSearchItemContext: Function,
 *   _getSearchItemGroupBys: Function,
 *   _getSelectedGeneratorIds: Function,
 *   _shouldWaitForData: Function,
 * }} SearchModelLike
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

export class SearchModel extends SearchQueryMixin(
    SearchSplitDomainMixin(
        SearchFavoritesMixin(SearchPropertiesMixin(SearchPanelMixin(EventBus))),
    ),
) {
    constructor(env, services, args) {
        super();
        this.env = env;
        this.setup(services, args);
    }

    setup(services, _args) {
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

        this.referenceMoment = DateTime.local();
        this.intervalOptions = getIntervalOptions();
        this.categoriesLoadId = 0;
        this.filtersLoadId = 0;
        /** @type {Map<number, number>} */
        this._sectionLoadIds = new Map();

        this._reloadMutex = new Mutex();
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
        /** @type {boolean | undefined} */
        this.defaultGroupByRemoved = undefined;
        /** @type {any} */
        this._filledPropertyFields = undefined;

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
            if (this.defaultGroupByRemoved) {
                this.defaultGroupBy = undefined;
            }
            this.__legacyParseSearchPanelArchAnyway(
                searchViewDescription,
                searchViewFields,
            );
            this.display = this._getDisplay(config.display);
            this._reconciliateFavorites();
            try {
                if (!this.searchPanelInfo.loaded) {
                    await this._reloadSections();
                }
            } finally {
                this._pendingNotification = false;
            }
            return;
        }

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

            this._activateDefaultSearchItems(
                activateFavorite ? defaultFavoriteId : null,
            );

            /** @type Map<number,Section> */
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
                        // A category consumes its default as a scalar, a filter
                        // as a list of value ids; nothing enforces the two forms
                        // apart, so accept the scalar a caller naturally writes.
                        // Falsy stays "no default", as before.
                        const rawDefault = searchPanelDefaults[fieldName];
                        const filterDefaults = rawDefault ? [].concat(rawDefault) : [];
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
            this._pendingNotification = false;
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

        this.globalContext =
            "context" in config ? toRaw({ ...(context || {}) }) : this.globalContext;
        this.globalDomain = "domain" in config ? domain || [] : this.globalDomain;
        this.globalGroupBy = "groupBy" in config ? groupBy || [] : this.globalGroupBy;
        this.globalOrderBy = "orderBy" in config ? orderBy || [] : this.globalOrderBy;

        this._extractSearchDefaultsFromGlobalContext();

        await this._reloadSections();
        await this._drainPendingNotification();
    }

    /**
     * @returns {Category[]}
     */
    get categories() {
        return /** @type {Category[]} */ (this._sectionsOfType("category"));
    }

    /**
     * Sections of a given type, memoized per `sections` Map. Keyed on the Map
     * itself rather than cleared in `_reset`: the Map is only ever replaced
     * wholesale (`load`, `_importState`), never added to, so an identity check
     * cannot go stale — and section *contents* changing (values, counters,
     * errors) does not change which sections have which type.
     * @param {string} type
     * @returns {Section[]}
     */
    _sectionsOfType(type) {
        if (this._sectionsByType?.source !== this.sections) {
            this._sectionsByType = { source: this.sections };
        }
        this._sectionsByType[type] ??= [...this.sections.values()].filter(
            (s) => s.type === type,
        );
        return this._sectionsByType[type];
    }

    /**
     * Raw memoized context. Also the value the public `context` getter now
     * returns directly (see there).
     * @returns {Context}
     */
    get _rawContext() {
        if (!this._context) {
            this._context = makeContext([this.globalContext, this._getContext()]);
            this._freezeInDevMode(this._context);
        }
        return this._context;
    }

    /**
     * Memoized context, returned by reference (frozen in dev) — same read-only
     * convention as `facets`/`getSections`. The former deep-copy-on-every-access
     * was redundant (makeContext already produced a detached object) and costly:
     * views re-read this on every SearchParams build, several times per search
     * interaction, over potentially large contexts.
     * @returns {Context} should be imported from context.js?
     */
    get context() {
        return this._rawContext;
    }

    /**
     * Memoized domain, returned by reference (frozen in dev). computeDomain
     * already JSON-round-trips into a detached structure, so the previous
     * per-access deep copy was pure overhead. See the `context` getter.
     * @returns {DomainListRepr}
     */
    get domain() {
        if (!this._domain) {
            this._domain = /** @type {DomainListRepr} */ (this._getDomain());
            this._freezeInDevMode(this._domain);
        }
        return this._domain;
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
        return /** @type {Filter[]} */ (this._sectionsOfType("filter"));
    }

    /**
     * Unlike `context`/`domain`/`orderBy`, this returns a FRESH array on every
     * access, and must keep doing so. `web.WithSearch` passes context, domain,
     * groupBy, orderBy and display down as slot props, and Owl skips
     * re-rendering a child whose props are all strictly identical
     * (`arePropsDifferent` in owl.es.js). The other four are stable references
     * within a query cycle, so this copy is the only thing that makes the view
     * subtree re-render on a `WithSearch` render that did not reset the memos —
     * see `search()`. `slice` rather than `deepCopy`: the entries are groupBy
     * specs (strings), so the recursion bought nothing; it is the identity that
     * is load-bearing, not the depth.
     * @returns {string[]}
     */
    get groupBy() {
        if (!this.searchMenuTypes.has("groupBy")) {
            return [];
        }
        if (!this._groupBy) {
            this._groupBy = this._getGroupBy();
        }
        return this._groupBy.slice();
    }

    /**
     * Memoized orderBy, returned by reference (frozen in dev). See the `context`
     * getter. Consumers (relational/graph/pivot models) only read or rebuild it.
     * @returns {OrderTerm[]}
     */
    get orderBy() {
        if (!this._orderBy) {
            this._orderBy = this._getOrderBy();
            this._freezeInDevMode(this._orderBy);
        }
        return this._orderBy;
    }

    get isDebugMode() {
        return !!this.env.debug;
    }

    /**
     * @returns {Object}
     */
    exportState() {
        const state = {};
        execute(mapToArray, this, state);
        return state;
    }

    /**
     * Return an array containing enriched copies of all searchElements or of those
     * satifying the given predicate if any
     * @param {(searchItem: Object) => boolean} [predicate]
     * @returns {Object[]}
     */
    getSearchItems(predicate) {
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
     * Re-run the current search (the search bar's Enter key and its magnifier).
     * The reset is what makes the update reach the view: consumers detect a
     * change by the identity of the context/domain/groupBy/orderBy slot props
     * `WithSearch` hands them, and without it every one of them is still the
     * memo from before — leaving `groupBy`'s copy-on-read as the only, accidental
     * reason the view re-renders at all (see the `groupBy` getter).
     */
    search() {
        this._reset();
        this.trigger(SearchModelEvent.UPDATE);
    }

    /**
     * Activate the default favorite (if any) or all default filters.
     */
    _activateDefaultSearchItems(defaultFavoriteId) {
        if (defaultFavoriteId) {
            this.toggleSearchItem(defaultFavoriteId);
        } else {
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

    _extractSearchDefaultsFromGlobalContext() {
        return extractSearchDefaults(this.globalContext);
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
        if (!this._groups) {
            this._groups = getQueryGroups(this.query, this.searchItems);
        }
        return this._groups;
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

    async _notify() {
        this._reset();

        if (this.blockNotification) {
            this._pendingNotification = true;
            return;
        }

        do {
            this._pendingNotification = false;
            await this._reloadSections();
        } while (this._pendingNotification);

        this.trigger(SearchModelEvent.UPDATE);
    }

    /**
     * Emit the notification a query mutation raised while a blocking window was
     * open, when that window was NOT opened by `_notify` itself (`reload`, and
     * any future async entry point that batches). `_notify`'s own do/while
     * drains its window; every other opener must drain here or the update is
     * lost for good — the flag has no other consumer, so the view would keep
     * showing results for the pre-mutation domain until the next interaction.
     *
     * Must be called after the blocking window is closed (and, for
     * `_reloadSections`, outside `_reloadMutex`): `_notify` re-enters
     * `_reloadSections`, which would deadlock on a mutex still held by the
     * caller.
     *
     * @returns {Promise<void>}
     */
    async _drainPendingNotification() {
        if (this.blockNotification || !this._pendingNotification) {
            return;
        }
        this._pendingNotification = false;
        await this._notify();
    }

    /**
     * Freeze a memoized getter result in dev mode to enforce the read-only
     * convention (shared with facets/getSections). Shallow (top-level) — enough
     * to catch an accidental push/splice or top-level key assignment — and a
     * no-op in production so the hot render path pays nothing.
     * @template T
     * @param {T} value
     * @returns {T}
     */
    _freezeInDevMode(value) {
        if (this.isDebugMode) {
            Object.freeze(value);
        }
        return value;
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
