// @ts-check

/** @module @web/search/search_panel/search_panel_state - Search panel section management extracted from SearchModel */

/**
 * Extracted search panel logic for SearchModel.
 *
 * Manages category/filter sections: fetching, tree creation, value toggling,
 * and reload logic. Receives the SearchModel instance as first argument
 * (delegation pattern), preserving subclass polymorphism.
 */

import { Domain } from "@web/core/domain";
import {
    createCategoryTree as buildCategoryTree,
    createFilterTree as buildFilterTree,
} from "./search_panel_fetch";
import { hasValues } from "../search_state";

/** @import { SearchModel, Category, Filter, Section, SectionPredicate } from "@web/search/search_model" */
/** @import { DomainListRepr } from "@web/core/domain" */

/**
 * Set the active value of a category.
 * @param {SearchModel} searchModel
 * @param {number} sectionId
 * @param {number} valueId
 */
export function toggleCategoryValue(searchModel, sectionId, valueId) {
    const category = searchModel.sections.get(sectionId);
    category.activeValueId = valueId;
    searchModel._notify();
}

/**
 * Toggle filter values on or off.
 * @param {SearchModel} searchModel
 * @param {number} sectionId
 * @param {number[]} valueIds
 * @param {boolean} [forceTo=null]
 */
export function toggleFilterValues(searchModel, sectionId, valueIds, forceTo = null) {
    const filter = searchModel.sections.get(sectionId);
    for (const valueId of valueIds) {
        const value = filter.values.get(valueId);
        value.checked = forceTo === null ? !value.checked : forceTo;
    }
    searchModel._notify();
}

/**
 * Clear all values from the provided sections.
 * @param {SearchModel} searchModel
 * @param {number[]} sectionIds
 */
export function clearSections(searchModel, sectionIds) {
    for (const sectionId of sectionIds) {
        const section = searchModel.sections.get(sectionId);
        if (section.type === "category") {
            section.activeValueId = false;
        } else {
            for (const [, value] of section.values) {
                value.checked = false;
            }
        }
    }
    searchModel._notify();
}

/**
 * Returns a sorted list of section copies, optionally filtered.
 * @param {SearchModel} searchModel
 * @param {SectionPredicate} [predicate]
 * @returns {Section[]}
 */
export function getSections(searchModel, predicate) {
    let sections = [...searchModel.sections.values()].map((section) => ({
        ...section,
        empty: !hasValues(section),
    }));
    if (predicate) {
        sections = sections.filter(predicate);
    }
    return sections.sort((s1, s2) => s1.index - s2.index);
}

/**
 * Build a category tree from ORM results.
 * @param {SearchModel} searchModel
 * @param {number} sectionId
 * @param {Object} result
 */
export function createCategoryTree(searchModel, sectionId, result) {
    const category = searchModel.sections.get(sectionId);
    buildCategoryTree(category, result, (cat, ids) =>
        searchModel._ensureCategoryValue(cat, ids),
    );
}

/**
 * Build a filter tree from ORM results.
 * @param {SearchModel} searchModel
 * @param {number} sectionId
 * @param {Object} result
 */
export function createFilterTree(searchModel, sectionId, result) {
    const filter = searchModel.sections.get(sectionId);
    buildFilterTree(filter, result);
}

/**
 * Ensure the active category value is among existing values.
 * @param {Category} category
 * @param {number[]} valueIds
 */
export function ensureCategoryValue(category, valueIds) {
    if (!valueIds.includes(category.activeValueId)) {
        category.activeValueId = valueIds[0];
    }
}

/**
 * Fetch values for each category at startup or reload.
 * @param {SearchModel} searchModel
 * @param {Category[]} categories
 * @returns {Promise}
 */
export async function fetchCategories(searchModel, categories) {
    const filterDomain = searchModel._getFilterDomain();
    const searchDomain = searchModel.searchDomain;
    const categoriesLoadId = ++searchModel.categoriesLoadId;
    await Promise.all(
        categories.map(async (category) => {
            const result = await searchModel.orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (result, hasChanged) => {
                        if (
                            !hasChanged ||
                            categoriesLoadId !== searchModel.categoriesLoadId
                        ) {
                            return;
                        }
                        searchModel._createCategoryTree(category.id, result);
                        searchModel._reset();
                        searchModel.trigger("update");
                    },
                })
                .call(
                    searchModel.resModel,
                    "search_panel_select_range",
                    [category.fieldName],
                    {
                        category_domain: searchModel._getCategoryDomain(category.id),
                        context: searchModel.globalContext,
                        enable_counters: category.enableCounters,
                        expand: category.expand,
                        filter_domain: filterDomain,
                        hierarchize: category.hierarchize,
                        limit: category.limit,
                        search_domain: searchDomain,
                    },
                );
            searchModel._createCategoryTree(category.id, result);
        }),
    );
}

/**
 * Fetch values for each filter section.
 * @param {SearchModel} searchModel
 * @param {Filter[]} filters
 * @returns {Promise}
 */
export async function fetchFilters(searchModel, filters) {
    const evalContext = {};
    for (const category of searchModel.categories) {
        evalContext[category.fieldName] = category.activeValueId;
    }
    const categoryDomain = searchModel._getCategoryDomain();
    const searchDomain = searchModel.searchDomain;
    const filtersLoadId = ++searchModel.filtersLoadId;
    await Promise.all(
        filters.map(async (filter) => {
            const result = await searchModel.orm
                .cache({
                    type: "disk",
                    update: "always",
                    callback: (result, hasChanged) => {
                        if (!hasChanged || filtersLoadId !== searchModel.filtersLoadId) {
                            return;
                        }
                        searchModel._createFilterTree(filter.id, result);
                        searchModel._reset();
                        searchModel.trigger("update");
                    },
                })
                .call(
                    searchModel.resModel,
                    "search_panel_select_multi_range",
                    [filter.fieldName],
                    {
                        category_domain: categoryDomain,
                        comodel_domain: new Domain(filter.domain).toList(
                            evalContext,
                        ),
                        context: searchModel.globalContext,
                        enable_counters: filter.enableCounters,
                        filter_domain: searchModel._getFilterDomain(filter.id),
                        expand: filter.expand,
                        group_by: filter.groupBy || false,
                        group_domain: searchModel._getGroupDomain(filter),
                        limit: filter.limit,
                        search_domain: searchDomain,
                    },
                );
            searchModel._createFilterTree(filter.id, result);
        }),
    );
}

/**
 * Fetch values for the given categories and filters.
 * @param {SearchModel} searchModel
 * @param {Category[]} categoriesToLoad
 * @param {Filter[]} filtersToLoad
 * @returns {Promise}
 */
export async function fetchSections(searchModel, categoriesToLoad, filtersToLoad) {
    await searchModel._fetchCategories(categoriesToLoad);
    await searchModel._fetchFilters(filtersToLoad);
    searchModel.searchPanelInfo.loaded = true;
}

/**
 * Reload sections when search domain changes or search panel becomes visible.
 * @param {SearchModel} searchModel
 * @returns {Promise<void>}
 */
export async function reloadSections(searchModel) {
    searchModel.blockNotification = true;

    const searchDomain = /** @type {DomainListRepr} */ (
        searchModel._getDomain({ withSearchPanel: false })
    );
    const searchDomainChanged =
        searchModel.searchPanelInfo.shouldReload ||
        JSON.stringify(searchModel.searchDomain) !== JSON.stringify(searchDomain);
    searchModel.searchDomain = searchDomain;

    const toFetch = (section) =>
        section.enableCounters || (searchDomainChanged && !section.expand);
    const categoriesToFetch = searchModel.categories.filter(toFetch);
    const filtersToFetch = searchModel.filters.filter(toFetch);

    if (
        searchDomainChanged ||
        Boolean(categoriesToFetch.length + filtersToFetch.length)
    ) {
        if (searchModel.display.searchPanel) {
            searchModel.sectionsPromise = searchModel._fetchSections(
                categoriesToFetch,
                filtersToFetch,
            );
            if (searchModel._shouldWaitForData(searchDomainChanged)) {
                await searchModel.sectionsPromise;
            }
        }
        searchModel.searchPanelInfo.shouldReload = !searchModel.display.searchPanel;
    }

    searchModel.blockNotification = false;
}

/**
 * Whether the query should wait for section data before proceeding.
 * @param {SearchModel} searchModel
 * @param {boolean} searchDomainChanged
 * @returns {boolean}
 */
export function shouldWaitForData(searchModel, searchDomainChanged) {
    if (
        searchModel.categories.length &&
        searchModel.filters.some((filter) => filter.domain !== "[]")
    ) {
        return true;
    }
    if (!searchModel.searchDomain.length) {
        return false;
    }
    return [...searchModel.sections.values()].some(
        (section) => !section.expand && searchDomainChanged,
    );
}
