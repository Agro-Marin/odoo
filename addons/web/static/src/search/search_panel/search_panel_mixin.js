// @ts-check
/** @odoo-module native */

/** @module @web/search/search_panel/search_panel_mixin - Search panel section management mixed into SearchModel */

import { Domain } from "@web/core/domain";
import { SearchModelEvent } from "@web/core/events";
import { deepEqual } from "@web/core/utils/collections/objects";

import { hasValues } from "../search_state.js";
import {
    createCategoryTree as buildCategoryTree,
    createFilterTree as buildFilterTree,
} from "./search_panel_fetch.js";

/** @import { Section } from "@web/search/search_model" */
/** @import { DomainListRepr } from "@web/core/domain" */
/** @typedef {Section & { type: "category" }} Category */
/** @typedef {Section & { type: "filter" }} Filter */
/** @typedef {(section: Section) => boolean} SectionPredicate */

/**
 * @param {any} error
 * @returns {string}
 */
function sectionErrorMessage(error) {
    return error.data?.message || error.message || String(error);
}

/**
 * Search panel category/filter section management for SearchModel.
 *
 * Mixed into SearchModel (``class SearchModel extends SearchPanelMixin(EventBus)``)
 * rather than kept as a sibling module of pass-``this`` functions: the methods
 * here live on the SearchModel prototype chain, so subclasses (e.g. enterprise
 * ``documents_search_model``) still override ``_createCategoryTree`` /
 * ``_getCategoryDomain`` / ``_ensureCategoryValue`` and reach them via ``super``.
 * Because every call routes through ``this``, an overridden ``_createCategoryTree``
 * is honoured by ``_fetchCategories`` without any proxy round-trip.
 *
 * State owned here but declared/initialised by SearchModel: ``sections`` (Map),
 * ``_sections`` (memo), ``_sectionLoadIds`` (Map), ``searchPanelInfo``,
 * ``searchDomain``, ``sectionsPromise``. Domain builders (``_getDomain``,
 * ``_getCategoryDomain``, ``_getFilterDomain``, ``_getGroupDomain``), ``_reset``,
 * ``_notify`` and the ``_reloadMutex`` live on SearchModel and are reached via
 * ``this``.
 *
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchPanelMixin = (Base) =>
    class extends Base {
        /**
         * Set the active value of a category.
         * @param {number} sectionId
         * @param {number} valueId
         */
        toggleCategoryValue(sectionId, valueId) {
            const category = this.sections.get(sectionId);
            category.activeValueId = valueId;
            this._notify();
        }

        /**
         * Toggle filter values on or off.
         * @param {number} sectionId
         * @param {number[]} valueIds
         * @param {boolean|null} [forceTo=null]
         */
        toggleFilterValues(sectionId, valueIds, forceTo = null) {
            const filter = this.sections.get(sectionId);
            for (const valueId of valueIds) {
                const value = filter.values.get(valueId);
                if (!value) {
                    continue;
                }
                value.checked = forceTo === null ? !value.checked : forceTo;
            }
            this._notify();
        }

        /**
         * Clear all values from the provided sections.
         * @param {number[]} sectionIds
         */
        clearSections(sectionIds) {
            for (const sectionId of sectionIds) {
                const section = this.sections.get(sectionId);
                if (section.type === "category") {
                    section.activeValueId = false;
                } else {
                    for (const [, value] of section.values) {
                        value.checked = false;
                    }
                }
            }
            this._notify();
        }

        /**
         * Returns a list of section copies, optionally filtered.
         * Section order is the ``sections`` Map insertion order (arch order).
         *
         * Memoised like _facets/_groups: SearchPanel hits this getter several
         * times per render. Cleared in _reset() and whenever a section is mutated
         * outside a query cycle (tree rebuilds, fetch error stamps); consumers
         * treat the returned sections as read-only.
         *
         * @param {SectionPredicate} [predicate]
         * @returns {Section[]}
         */
        getSections(predicate) {
            if (!this._sections) {
                this._sections = [...this.sections.values()].map((section) => ({
                    ...section,
                    empty: !hasValues(section),
                }));
            }
            let sections = this._sections;
            if (predicate) {
                sections = sections.filter(predicate);
            }
            return sections;
        }

        /**
         * Build a category tree from ORM results.
         * @param {number} sectionId
         * @param {Object} result
         */
        _createCategoryTree(sectionId, result) {
            const category = this.sections.get(sectionId);
            buildCategoryTree(category, result, (cat, ids) =>
                this._ensureCategoryValue(cat, ids),
            );
            this._sections = null;
        }

        /**
         * Build a filter tree from ORM results.
         * @param {number} sectionId
         * @param {Object} result
         */
        _createFilterTree(sectionId, result) {
            const filter = this.sections.get(sectionId);
            buildFilterTree(filter, result);
            this._sections = null;
        }

        /**
         * Ensure the active category value is among existing values.
         * @param {Category} category
         * @param {number[]} valueIds
         */
        _ensureCategoryValue(category, valueIds) {
            if (!valueIds.includes(category.activeValueId)) {
                category.activeValueId = valueIds[0];
            }
        }

        /**
         * Fetch values for each category at startup or reload.
         * @param {Category[]} categories
         * @returns {Promise}
         */
        async _fetchCategories(categories) {
            const filterDomain = this._getFilterDomain();
            const searchDomain = this.searchDomain;
            await Promise.all(
                categories.map(async (category) => {
                    const loadId = (this._sectionLoadIds.get(category.id) || 0) + 1;
                    this._sectionLoadIds.set(category.id, loadId);
                    let result;
                    try {
                        result = await this.orm
                            .cache({
                                type: "disk",
                                update: "always",
                                callback: (result, hasChanged) => {
                                    if (
                                        !hasChanged ||
                                        loadId !== this._sectionLoadIds.get(category.id)
                                    ) {
                                        return;
                                    }
                                    this._createCategoryTree(category.id, result);
                                    this._reset();
                                    this.trigger(SearchModelEvent.UPDATE);
                                },
                            })
                            .call(
                                this.resModel,
                                "search_panel_select_range",
                                [category.fieldName],
                                {
                                    category_domain: this._getCategoryDomain(
                                        category.id,
                                    ),
                                    context: this.globalContext,
                                    enable_counters: category.enableCounters,
                                    expand: category.expand,
                                    filter_domain: filterDomain,
                                    hierarchize: category.hierarchize,
                                    limit: category.limit,
                                    search_domain: searchDomain,
                                },
                            );
                    } catch (error) {
                        if (loadId === this._sectionLoadIds.get(category.id)) {
                            this._createCategoryTree(category.id, {
                                error_msg: sectionErrorMessage(error),
                                values: [],
                            });
                        }
                        return;
                    }
                    if (loadId !== this._sectionLoadIds.get(category.id)) {
                        return;
                    }
                    this._createCategoryTree(category.id, result);
                }),
            );
        }

        /**
         * Fetch values for each filter section.
         * @param {Filter[]} filters
         * @returns {Promise}
         */
        async _fetchFilters(filters) {
            const evalContext = {};
            for (const category of this.categories) {
                evalContext[category.fieldName] = category.activeValueId;
            }
            const categoryDomain = this._getCategoryDomain();
            const searchDomain = this.searchDomain;
            await Promise.all(
                filters.map(async (filter) => {
                    const loadId = (this._sectionLoadIds.get(filter.id) || 0) + 1;
                    this._sectionLoadIds.set(filter.id, loadId);
                    let result;
                    try {
                        result = await this.orm
                            .cache({
                                type: "disk",
                                update: "always",
                                callback: (result, hasChanged) => {
                                    if (
                                        !hasChanged ||
                                        loadId !== this._sectionLoadIds.get(filter.id)
                                    ) {
                                        return;
                                    }
                                    this._createFilterTree(filter.id, result);
                                    this._reset();
                                    this.trigger(SearchModelEvent.UPDATE);
                                },
                            })
                            .call(
                                this.resModel,
                                "search_panel_select_multi_range",
                                [filter.fieldName],
                                {
                                    category_domain: categoryDomain,
                                    comodel_domain: new Domain(filter.domain).toList(
                                        evalContext,
                                    ),
                                    context: this.globalContext,
                                    enable_counters: filter.enableCounters,
                                    filter_domain: this._getFilterDomain(filter.id),
                                    expand: filter.expand,
                                    group_by: filter.groupBy || false,
                                    group_domain: this._getGroupDomain(filter),
                                    limit: filter.limit,
                                    search_domain: searchDomain,
                                },
                            );
                    } catch (error) {
                        if (loadId === this._sectionLoadIds.get(filter.id)) {
                            this._createFilterTree(filter.id, {
                                error_msg: sectionErrorMessage(error),
                                values: [],
                            });
                        }
                        return;
                    }
                    if (loadId !== this._sectionLoadIds.get(filter.id)) {
                        return;
                    }
                    this._createFilterTree(filter.id, result);
                }),
            );
        }

        /**
         * Fetch values for the given categories and filters.
         * @param {Category[]} categoriesToLoad
         * @param {Filter[]} filtersToLoad
         * @returns {Promise}
         */
        async _fetchSections(categoriesToLoad, filtersToLoad) {
            await this._fetchCategories(categoriesToLoad);
            await this._fetchFilters(filtersToLoad);
            this.searchPanelInfo.loaded = true;
        }

        /**
         * Reload sections when search domain changes or search panel becomes visible.
         * Serialised through ``_reloadMutex`` (owned by SearchModel).
         * @returns {Promise<void>}
         */
        async _reloadSections() {
            return this._reloadMutex.exec(async () => {
                const wasBlocked = this.blockNotification;
                this.blockNotification = true;
                try {
                    const searchDomain = /** @type {DomainListRepr} */ (
                        this._getDomain({ withSearchPanel: false })
                    );
                    const searchDomainChanged =
                        this.searchPanelInfo.shouldReload ||
                        !deepEqual(this.searchDomain, searchDomain);
                    this.searchDomain = searchDomain;

                    const toFetch = (section) =>
                        section.enableCounters ||
                        (searchDomainChanged && !section.expand);
                    const categoriesToFetch = this.categories.filter(toFetch);
                    const filtersToFetch = this.filters.filter(toFetch);

                    if (
                        searchDomainChanged ||
                        Boolean(categoriesToFetch.length + filtersToFetch.length)
                    ) {
                        if (this.display.searchPanel) {
                            this.sectionsPromise = this._fetchSections(
                                categoriesToFetch,
                                filtersToFetch,
                            );
                            if (this._shouldWaitForData(searchDomainChanged)) {
                                await this.sectionsPromise;
                            }
                        }
                        this.searchPanelInfo.shouldReload = !this.display.searchPanel;
                    }
                } finally {
                    this.blockNotification = wasBlocked;
                }
            });
        }

        /**
         * Whether the query should wait for section data before proceeding.
         * @param {boolean} searchDomainChanged
         * @returns {boolean}
         */
        _shouldWaitForData(searchDomainChanged) {
            if (
                this.categories.length &&
                this.filters.some((filter) => filter.domain !== "[]")
            ) {
                return true;
            }
            if (!this.searchDomain?.length || !searchDomainChanged) {
                return false;
            }
            return [...this.sections.values()].some((section) => !section.expand);
        }
    };
