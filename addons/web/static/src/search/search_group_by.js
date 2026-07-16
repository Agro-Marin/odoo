// @ts-check
/** @odoo-module native */

/** @module search/search_group_by - GroupBy/OrderBy computation utilities for SearchModel */

import { rankInterval } from "./utils/dates.js";

/**
 * Reconstruct (active) groups from query elements and search items.
 *
 * @param {Object[]} query
 * @param {Object} searchItems
 * @returns {Object[]}
 */
export function getQueryGroups(query, searchItems) {
    // Map keyed by groupId (and, per group, by searchItemId) instead of the
    // former O(q²) `Array.find` scans: getQueryGroups is on the hot _getGroups
    // spine. `preGroups`/`activeItems` arrays are kept alongside the maps to
    // preserve query (insertion) order, which downstream group/facet order
    // relies on.
    const preGroupMap = new Map();
    const preGroups = [];
    for (const queryElem of query) {
        const { searchItemId } = queryElem;
        const { groupId } = searchItems[searchItemId];
        let preGroup = preGroupMap.get(groupId);
        if (!preGroup) {
            preGroup = { id: groupId, queryElements: [] };
            preGroupMap.set(groupId, preGroup);
            preGroups.push(preGroup);
        }
        preGroup.queryElements.push(queryElem);
    }
    const groups = [];
    for (const preGroup of preGroups) {
        const { queryElements, id } = preGroup;
        const activeItemMap = new Map();
        const activeItems = [];
        const ensureActiveItem = (searchItemId, init) => {
            let activeItem = activeItemMap.get(searchItemId);
            if (!activeItem) {
                activeItem = { searchItemId, ...init };
                activeItemMap.set(searchItemId, activeItem);
                activeItems.push(activeItem);
            }
            return activeItem;
        };
        for (const queryElem of queryElements) {
            const { searchItemId } = queryElem;
            if ("generatorId" in queryElem) {
                ensureActiveItem(searchItemId, { generatorIds: [] }).generatorIds.push(
                    queryElem.generatorId,
                );
            } else if ("intervalId" in queryElem) {
                ensureActiveItem(searchItemId, { intervalIds: [] }).intervalIds.push(
                    queryElem.intervalId,
                );
            } else if ("autocompleteValue" in queryElem) {
                ensureActiveItem(searchItemId, {
                    autocompleteValues: [],
                }).autocompleteValues.push(queryElem.autocompleteValue);
            } else {
                ensureActiveItem(searchItemId, {});
            }
        }
        for (const activeItem of activeItems) {
            if ("intervalIds" in activeItem) {
                activeItem.intervalIds.sort(
                    (g1, g2) => rankInterval(g1) - rankInterval(g2),
                );
            }
        }
        groups.push({ id, activeItems });
    }
    return groups;
}

/**
 * Compute group-bys for a single active search item.
 *
 * @param {Object} activeItem
 * @param {Object} searchItems
 * @returns {string[]|null}
 */
export function computeSearchItemGroupBys(activeItem, searchItems) {
    const { searchItemId } = activeItem;
    const searchItem = searchItems[searchItemId];
    switch (searchItem.type) {
        case "dateGroupBy": {
            const { fieldName } = searchItem;
            return activeItem.intervalIds.map(
                (intervalId) => `${fieldName}:${intervalId}`,
            );
        }
        case "groupBy":
            return [searchItem.fieldName];
        case "favorite":
            return searchItem.groupBys;
        default:
            return null;
    }
}

/**
 * Compute the full list of group-bys from all active groups.
 *
 * @param {Object} params
 * @param {Object[]} params.groups
 * @param {string[]} params.globalGroupBy
 * @param {string[]} [params.defaultGroupBy]
 * @param {boolean} params.fallbackOnDefault
 * @param {Function} params.getSearchItemGroupBys - (activeItem) => string[]|null
 * @returns {string[]}
 */
export function computeGroupBy({
    groups,
    globalGroupBy,
    defaultGroupBy,
    fallbackOnDefault,
    getSearchItemGroupBys,
}) {
    const groupBys = [];
    for (const group of groups) {
        for (const activeItem of group.activeItems) {
            const activeItemGroupBys = getSearchItemGroupBys(activeItem);
            if (activeItemGroupBys) {
                groupBys.push(...activeItemGroupBys);
            }
        }
    }
    // All three sources (query group-bys, globalGroupBy, defaultGroupBy) are
    // string[]; the former `typeof groupBy === "string"` normalization was dead.
    return groupBys.length
        ? groupBys
        : globalGroupBy.length
          ? globalGroupBy.slice()
          : (fallbackOnDefault && defaultGroupBy?.slice()) || [];
}

/**
 * @typedef {{ name: string, asc?: boolean }} OrderTerm
 */

/**
 * Compute the order-by from active groups.
 *
 * @param {Object[]} groups
 * @param {Object} searchItems
 * @param {string[]} groupBy - current groupBy result
 * @param {string|false} orderByCount
 * @param {OrderTerm[]} globalOrderBy
 * @returns {OrderTerm[]}
 */
export function computeOrderBy(
    groups,
    searchItems,
    groupBy,
    orderByCount,
    globalOrderBy,
) {
    const orderBy = [];
    if (groupBy.length && orderByCount) {
        orderBy.push({ name: "__count", asc: orderByCount === "Asc" });
    }
    for (const group of groups) {
        for (const activeItem of group.activeItems) {
            const { searchItemId } = activeItem;
            const searchItem = searchItems[searchItemId];
            if (searchItem.type === "favorite") {
                orderBy.push(...searchItem.orderBy);
            }
        }
    }
    return orderBy.length ? orderBy : globalOrderBy;
}

/**
 * Get selected generator ids for a date filter from the query.
 *
 * @param {Object[]} query
 * @param {number} dateFilterId
 * @returns {Array}
 */
export function getSelectedGeneratorIds(query, dateFilterId) {
    const selectedOptionIds = [];
    for (const queryElem of query) {
        if (queryElem.searchItemId === dateFilterId && "generatorId" in queryElem) {
            selectedOptionIds.push(queryElem.generatorId);
        }
    }
    return selectedOptionIds;
}
