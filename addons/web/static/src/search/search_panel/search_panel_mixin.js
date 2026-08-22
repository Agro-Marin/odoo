// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
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
 * @template {new (...args: any[]) => any} T
 * @param {T} Base
 */
export const SearchPanelMixin = (Base) =>
    class extends Base {
        /**
         * @param {number} sectionId
         * @param {number} valueId
         */
        async toggleCategoryValue(sectionId, valueId) {
            const category = this.sections.get(sectionId);
            category.activeValueId = valueId;
            return this._notify();
        }

        /**
         * @param {number} sectionId
         * @param {number[]} valueIds
         * @param {boolean|null} [forceTo=null]
         */
        async toggleFilterValues(sectionId, valueIds, forceTo = null) {
            const filter = this.sections.get(sectionId);
            for (const valueId of valueIds) {
                const value = filter.values.get(valueId);
                if (!value) {
                    continue;
                }
                value.checked = forceTo === null ? !value.checked : forceTo;
            }
            return this._notify();
        }

        /**
         * @param {number[]} sectionIds
         */
        async clearSections(sectionIds) {
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
            return this._notify();
        }

        /**
         * @returns {Promise<void>}
         */
        async invalidateSections() {
            this.searchPanelInfo.shouldReload = true;
            return this._notify();
        }

        /**
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
         * @param {number} sectionId
         * @param {Record<string, any>} result
         */
        _createCategoryTree(sectionId, result) {
            const category = this.sections.get(sectionId);
            buildCategoryTree(
                category,
                result,
                (/** @type {any} */ cat, /** @type {any} */ ids) =>
                    this._ensureCategoryValue(cat, ids),
            );
            this._sections = null;
        }

        /**
         * @param {number} sectionId
         * @param {Record<string, any>} result
         */
        _createFilterTree(sectionId, result) {
            const filter = this.sections.get(sectionId);
            buildFilterTree(filter, result);
            this._sections = null;
        }

        /**
         * @param {Category} category
         * @param {number[]} valueIds
         */
        _ensureCategoryValue(category, valueIds) {
            if (!valueIds.includes(category.activeValueId)) {
                category.activeValueId = valueIds[0];
            }
        }

        /**
         * @param {Category[]} categories
         * @returns {Promise<void>}
         */
        async _fetchCategories(categories) {
            const filterDomain = this._getFilterDomain();
            const searchDomain = this.searchDomain;
            await Promise.all(
                categories.map(async (category) => {
                    const loadId = (this._sectionLoadIds.get(category.id) || 0) + 1;
                    this._sectionLoadIds.set(category.id, loadId);
                    const kwargs = {
                        category_domain: this._getCategoryDomain(category.id),
                        context: this.globalContext,
                        enable_counters: category.enableCounters,
                        expand: category.expand,
                        filter_domain: filterDomain,
                        hierarchize: category.hierarchize,
                        limit: category.limit,
                        search_domain: searchDomain,
                    };
                    let result;
                    try {
                        result = await this.orm
                            .cache({
                                type: "disk",
                                update: "always",
                                callback: (
                                    /** @type {any} */ result,
                                    /** @type {any} */ hasChanged,
                                ) => {
                                    if (
                                        !hasChanged ||
                                        loadId !== this._sectionLoadIds.get(category.id)
                                    ) {
                                        return;
                                    }
                                    this._createCategoryTree(category.id, result);
                                    this._notify({ reloadSections: false });
                                },
                            })
                            .call(
                                this.resModel,
                                "search_panel_select_range",
                                [category.fieldName],
                                kwargs,
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
         * @param {Filter[]} filters
         * @returns {Promise<void>}
         */
        async _fetchFilters(filters) {
            /** @type {Record<string, any>} */
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
                    const kwargs = {
                        category_domain: categoryDomain,
                        comodel_domain: new Domain(filter.domain).toList(evalContext),
                        context: this.globalContext,
                        enable_counters: filter.enableCounters,
                        filter_domain: this._getFilterDomain(filter.id),
                        expand: filter.expand,
                        group_by: filter.groupBy || false,
                        group_domain: this._getGroupDomain(filter),
                        limit: filter.limit,
                        search_domain: searchDomain,
                    };
                    let result;
                    try {
                        result = await this.orm
                            .cache({
                                type: "disk",
                                update: "always",
                                callback: (
                                    /** @type {any} */ result,
                                    /** @type {any} */ hasChanged,
                                ) => {
                                    if (
                                        !hasChanged ||
                                        loadId !== this._sectionLoadIds.get(filter.id)
                                    ) {
                                        return;
                                    }
                                    this._createFilterTree(filter.id, result);
                                    this._notify({ reloadSections: false });
                                },
                            })
                            .call(
                                this.resModel,
                                "search_panel_select_multi_range",
                                [filter.fieldName],
                                kwargs,
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
         * @param {Category[]} categoriesToLoad
         * @param {Filter[]} filtersToLoad
         * @returns {Promise<void>}
         */
        async _fetchSections(categoriesToLoad, filtersToLoad) {
            await this._fetchCategories(categoriesToLoad);
            await this._fetchFilters(filtersToLoad);
            this.searchPanelInfo.loaded = true;
        }

        /**
         * @returns {Promise<void>}
         */
        async _reloadSections() {
            return this._reloadMutex.exec(async () => {
                const wasBlocked = /** @type {boolean} */ (this.blockNotification);
                this.blockNotification = /** @type {boolean} */ (true);
                try {
                    const searchDomain = /** @type {DomainListRepr} */ (
                        this._getDomain({ withSearchPanel: false })
                    );
                    const searchDomainChanged =
                        this.searchPanelInfo.shouldReload ||
                        !deepEqual(this.searchDomain, searchDomain);
                    this.searchDomain = searchDomain;

                    const toFetch = (/** @type {any} */ section) =>
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
                    this.blockNotification = /** @type {boolean} */ (wasBlocked);
                }
            });
        }

        /**
         * @param {boolean} searchDomainChanged
         * @returns {boolean}
         */
        _shouldWaitForData(searchDomainChanged) {
            if (
                this.categories.length &&
                this.filters.some((/** @type {any} */ filter) => filter.domain !== "[]")
            ) {
                return true;
            }
            if (!this.searchDomain?.length || !searchDomainChanged) {
                return false;
            }
            return [...this.sections.values()].some((section) => !section.expand);
        }
    };
