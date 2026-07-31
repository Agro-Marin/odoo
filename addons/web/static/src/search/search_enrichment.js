// @ts-check
/** @odoo-module native */

/** @module @web/search/search_enrichment */

import { getPeriodOptions } from "./utils/dates.js";

/**
 * @param {Object[]} options
 * @param {Array} selectedIds
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
 * @param {Object} searchItem
 * @param {Object[] | Map<number, Object[]>} query
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
