// @ts-check
/** @odoo-module native */

/** @module @web/search/search_enrichment - Pure search-item enrichment producing activated copies with period/interval metadata */

import { getPeriodOptions } from "./utils/dates.js";

/**
 * Enrich option descriptors with an `isActive` flag.
 *
 * @param {Object[]} options
 * @param {Array} selectedIds - currently selected option ids
 * @returns {Object[]}
 */
function enrichOptions(options, selectedIds) {
    return options.map((o) => {
        const { description, id, groupNumber } = o;
        const isActive = selectedIds.some((optionId) => optionId === id);
        return { description, id, groupNumber, isActive };
    });
}

/**
 * Index the query elements by the search item they belong to.
 *
 * Enrichment is a whole-model pass, so scanning the query once here beats
 * re-filtering it inside every item (`items × query` comparisons per query
 * cycle, on a hot render path).
 *
 * @param {Object[]} query
 * @returns {Map<number, Object[]>}
 */
export function indexQueryBySearchItem(query) {
    /** @type {Map<number, Object[]>} */
    const index = new Map();
    for (const queryElem of query) {
        const elements = index.get(queryElem.searchItemId);
        if (elements) {
            elements.push(queryElem);
        } else {
            index.set(queryElem.searchItemId, [queryElem]);
        }
    }
    return index;
}

/**
 * Return an enriched copy of `searchItem` with activation status and
 * type-specific metadata (options, autocomplete values).
 *
 * Always returns an item — visibility is decided by the caller
 * (`getSearchItems` evaluates the item's `invisible` expression).
 *
 * @param {Object} searchItem
 * @param {Object[] | Map<number, Object[]>} query - current query elements, or
 *  the {@link indexQueryBySearchItem} index of them
 * @param {any} referenceMoment
 * @param {Object[]} intervalOptions
 * @returns {Object}
 */
export function enrichSearchItem(searchItem, query, referenceMoment, intervalOptions) {
    if (searchItem.type === "field" && searchItem.fieldType === "properties") {
        return { ...searchItem };
    }
    const queryElements =
        query instanceof Map
            ? query.get(searchItem.id) || []
            : query.filter((queryElem) => queryElem.searchItemId === searchItem.id);
    const isActive = Boolean(queryElements.length);
    const enrichedSearchItem = Object.assign({ isActive }, searchItem);
    switch (searchItem.type) {
        case "dateFilter":
            enrichedSearchItem.options = enrichOptions(
                searchItem.optionsParams
                    ? getPeriodOptions(referenceMoment, searchItem.optionsParams)
                    : [],
                queryElements.map((queryElem) => queryElem.generatorId),
            );
            break;
        case "dateGroupBy":
            enrichedSearchItem.options = enrichOptions(
                intervalOptions,
                queryElements.map((queryElem) => queryElem.intervalId),
            );
            break;
        case "field":
        case "field_property":
            enrichedSearchItem.autocompleteValues = queryElements.map(
                (queryElem) => queryElem.autocompleteValue,
            );
            break;
    }
    return enrichedSearchItem;
}
