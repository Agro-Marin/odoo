// @ts-check
/** @odoo-module native */

import { getPeriodOptions } from "./utils/dates.js";

/** @import { AutocompleteValue, EnrichedOption, EnrichedSearchItem, QueryElement, StoredSearchItem } from "./search_types" */

/**
 * @param {readonly Record<string, any>[]} options
 * @param {any[]} selectedIds
 * @returns {EnrichedOption[]}
 */
function enrichOptions(options, selectedIds) {
    return options.map((o) => {
        const { description, id, groupNumber } = o;
        const isActive = selectedIds.some((optionId) => optionId === id);
        return { description, id, groupNumber, isActive };
    });
}

/**
 * @param {QueryElement[]} query
 * @returns {Map<number, QueryElement[]>}
 */
export function indexQueryBySearchItem(query) {
    /** @type {Map<number, QueryElement[]>} */
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
 * @param {StoredSearchItem} searchItem
 * @param {QueryElement[] | Map<number, QueryElement[]>} query
 * @param {any} referenceMoment
 * @param {Record<string, any>[]} intervalOptions
 * @returns {EnrichedSearchItem}
 */
export function enrichSearchItem(searchItem, query, referenceMoment, intervalOptions) {
    const queryElements =
        query instanceof Map
            ? query.get(searchItem.id) || []
            : query.filter((queryElem) => queryElem.searchItemId === searchItem.id);
    const isActive = Boolean(queryElements.length);
    /** @type {EnrichedSearchItem} */
    const enrichedSearchItem = Object.assign({ isActive }, searchItem);
    if (searchItem.type === "field" && searchItem.fieldType === "properties") {
        return enrichedSearchItem;
    }
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
            enrichedSearchItem.autocompleteValues = queryElements
                .map((queryElem) => queryElem.autocompleteValue)
                .filter((value) => value !== undefined);
            break;
    }
    return enrichedSearchItem;
}
