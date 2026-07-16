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
 * Return an enriched copy of `searchItem` with activation status and
 * type-specific metadata (options, autocomplete values), or `null` if hidden.
 *
 * @param {Object} searchItem
 * @param {Object[]} query - current query elements
 * @param {any} referenceMoment
 * @param {Object[]} intervalOptions
 * @returns {Object | null}
 */
export function enrichSearchItem(searchItem, query, referenceMoment, intervalOptions) {
    if (searchItem.type === "field" && searchItem.fieldType === "properties") {
        return { ...searchItem };
    }
    const queryElements = query.filter(
        (queryElem) => queryElem.searchItemId === searchItem.id,
    );
    const isActive = Boolean(queryElements.length);
    const enrichedSearchItem = Object.assign({ isActive }, searchItem);
    switch (searchItem.type) {
        case "dateFilter":
            // `optionsParams` may be absent — toggleDateFilter deliberately
            // tolerates such items (explicit generatorId, unit tests) via its
            // knownOptions guard. getPeriodOptions destructures optionsParams and
            // would throw, crashing getSearchItems() (hence the whole
            // SearchBarMenu render) on an item the mutation path accepts. Fall
            // back to no options.
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
