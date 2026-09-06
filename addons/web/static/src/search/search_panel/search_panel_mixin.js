// @ts-check
/** @odoo-module native */

import { Domain } from "@web/core/domain";
import { deepEqual } from "@web/core/utils/collections/objects";

import { hasValues } from "../search_state.js";
import {
    createCategoryTree as buildCategoryTree,
    createFilterTree as buildFilterTree,
} from "./search_panel_fetch.js";

/** @import { DomainListRepr } from "@web/core/domain" */
/** @import { Category, Filter, Section, SectionPredicate } from "../search_types" */

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
         * @param {Section} section
         * @param {Record<string, any>} result
         */
        _createSectionTree(section, result) {
            if (section.type === "category") {
                this._createCategoryTree(section.id, result);
            } else {
                this._createFilterTree(section.id, result);
            }
        }

        /**
         * Fetch one section's values, keeping only the response of the latest
         * fetch issued for it: an earlier response landing later, from the
         * network or from the disk cache's refresh callback, is dropped.
         *
         * @param {Section} section
         * @param {string} method
         * @param {Record<string, any>} kwargs
         * @returns {Promise<void>}
         */
        async _fetchSection(section, method, kwargs) {
            const loadId = (this._sectionLoadIds.get(section.id) || 0) + 1;
            this._sectionLoadIds.set(section.id, loadId);
            const isLatest = () => loadId === this._sectionLoadIds.get(section.id);
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
                            if (!hasChanged || !isLatest()) {
                                return;
                            }
                            this._createSectionTree(section, result);
                            this._notify({ reloadSections: false });
                        },
                    })
                    .call(this.resModel, method, [section.fieldName], kwargs);
            } catch (error) {
                if (isLatest()) {
                    this._createSectionTree(section, {
                        error_msg: sectionErrorMessage(error),
                        values: [],
                    });
                }
                return;
            }
            if (isLatest()) {
                this._createSectionTree(section, result);
            }
        }

        /**
         * @param {Category[]} categories
         * @returns {Promise<void>}
         */
        async _fetchCategories(categories) {
            const filterDomain = this._getFilterDomain();
            await Promise.all(
                categories.map((category) =>
                    this._fetchSection(category, "search_panel_select_range", {
                        category_domain: this._getCategoryDomain(category.id),
                        context: this.globalContext,
                        enable_counters: category.enableCounters,
                        expand: category.expand,
                        filter_domain: filterDomain,
                        hierarchize: category.hierarchize,
                        limit: category.limit,
                        search_domain: this.searchDomain,
                    }),
                ),
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
            await Promise.all(
                filters.map((filter) =>
                    this._fetchSection(filter, "search_panel_select_multi_range", {
                        category_domain: categoryDomain,
                        comodel_domain: new Domain(filter.domain).toList(evalContext),
                        context: this.globalContext,
                        enable_counters: filter.enableCounters,
                        filter_domain: this._getFilterDomain(filter.id),
                        expand: filter.expand,
                        group_by: filter.groupBy || false,
                        group_domain: this._getGroupDomain(filter),
                        limit: filter.limit,
                        search_domain: this.searchDomain,
                    }),
                ),
            );
        }

        /**
         * First load of every section, with the filter values the context's
         * `searchpanel_default_*` keys pre-checked. Awaited when a default
         * was given or the data gates the first query.
         *
         * @param {Record<string, any>} searchPanelDefaults
         * @returns {Promise<void>}
         */
        async _seedSearchPanel(searchPanelDefaults) {
            this.searchDomain = /** @type {DomainListRepr} */ (
                this._getDomain({ withSearchPanel: false })
            );
            for (const { fieldName, values } of this.filters) {
                const rawDefault = searchPanelDefaults[fieldName];
                for (const valueId of rawDefault ? [].concat(rawDefault) : []) {
                    values.set(valueId, { id: valueId, checked: true });
                }
            }
            this._sections = null;
            this.sectionsPromise = this._fetchSections(this.categories, this.filters);
            if (
                Object.keys(searchPanelDefaults).length ||
                this._shouldWaitForData(false)
            ) {
                await this.sectionsPromise;
            }
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
            return this._reloadMutex.exec(() =>
                this._withNotificationsBlockedAsync(async () => {
                    const searchDomain = /** @type {DomainListRepr} */ (
                        this._getDomain({ withSearchPanel: false })
                    );
                    const searchDomainChanged =
                        this.searchPanelInfo.shouldReload ||
                        !deepEqual(this.searchDomain, searchDomain);
                    this.searchDomain = searchDomain;

                    const toFetch = (/** @type {Section} */ section) =>
                        section.enableCounters ||
                        (searchDomainChanged && !section.expand);
                    const categoriesToFetch = this.categories.filter(toFetch);
                    const filtersToFetch = this.filters.filter(toFetch);

                    if (
                        searchDomainChanged ||
                        categoriesToFetch.length ||
                        filtersToFetch.length
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
                }),
            );
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
