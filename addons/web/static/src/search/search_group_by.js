// @ts-check
/** @odoo-module native */

import { rankInterval } from "./utils/dates.js";

/** @import { ActiveItem, QueryElement, QueryGroup, SearchItems } from "./search_types" */

/**
 * @param {QueryElement[]} query
 * @param {SearchItems} searchItems
 * @returns {QueryGroup[]}
 */
export function getQueryGroups(query, searchItems) {
    /** @type {Map<number, {id: number, queryElements: QueryElement[]}>} */
    const preGroupMap = new Map();
    /** @type {{id: number, queryElements: QueryElement[]}[]} */
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
    /** @type {QueryGroup[]} */
    const groups = [];
    for (const preGroup of preGroups) {
        const { queryElements, id } = preGroup;
        /** @type {Map<number, ActiveItem>} */
        const activeItemMap = new Map();
        /** @type {ActiveItem[]} */
        const activeItems = [];
        /**
         * @param {number} searchItemId
         * @param {Partial<ActiveItem>} init
         * @returns {any}
         */
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
                    (/** @type {string} */ g1, /** @type {string} */ g2) =>
                        rankInterval(g1) - rankInterval(g2),
                );
            }
        }
        groups.push({ id, activeItems });
    }
    return groups;
}

/**
 * @param {SearchItems} searchItems
 * @returns {number|undefined}
 */
export function findGroupByGroupId(searchItems) {
    const firstGroupBy = Object.values(searchItems).find((searchItem) =>
        ["groupBy", "dateGroupBy"].includes(searchItem.type),
    );
    return firstGroupBy?.groupId;
}

/**
 * @param {ActiveItem} activeItem
 * @param {SearchItems} searchItems
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
 * @param {object} params
 * @param {QueryGroup[]} params.groups
 * @param {string[]} params.globalGroupBy
 * @param {string[]} [params.defaultGroupBy]
 * @param {boolean} params.fallbackOnDefault
 * @param {Function} params.getSearchItemGroupBys
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
 * @param {QueryGroup[]} groups
 * @param {SearchItems} searchItems
 * @param {string[]} groupBy
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
                orderBy.push(...searchItem.orderBy.map((term) => ({ ...term })));
            }
        }
    }
    return orderBy.length ? orderBy : globalOrderBy.slice();
}

/**
 * @param {QueryElement[]} query
 * @param {number} dateFilterId
 * @returns {any[]}
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
