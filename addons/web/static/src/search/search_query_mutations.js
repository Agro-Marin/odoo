// @ts-check
/** @odoo-module native */

/** @module @web/search/search_query_mutations - Query mutation methods extracted from SearchModel */

/**
 * Extracted query mutation logic for SearchModel.
 *
 * Receives the SearchModel instance as first argument (delegation pattern),
 * preserving subclass polymorphism for all internal method calls.
 */

import { RpcEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { rpcBus } from "@web/core/network/rpc";

import {
    FAVORITE_PRIVATE_GROUP,
    FAVORITE_SHARED_GROUP,
    SPECIAL,
} from "./search_state.js";
import { DEFAULT_INTERVAL, getPeriodOptions, yearSelected } from "./utils/dates.js";

/** SearchModel widened so this delegate module can read instance state
 * set across SearchModel's many methods. */
/** @typedef {any} SearchModel */

/**
 * Deactivate the order-by-count flag when no active groupBy/dateGroupBy exists.
 * @param {SearchModel} searchModel
 */
function checkOrderByCountStatus(searchModel) {
    if (
        searchModel.orderByCount &&
        !searchModel.query.some((item) =>
            ["dateGroupBy", "groupBy"].includes(
                searchModel.searchItems[item.searchItemId].type,
            ),
        )
    ) {
        searchModel.orderByCount = false;
    }
}

/**
 * Run `fn` with search-model notifications blocked, restoring the previous
 * `blockNotification` state afterwards — even if `fn` throws.
 *
 * A raw `blockNotification = true; …; blockNotification = false` window has two
 * failure modes this guards against:
 *   - a throw inside the window (e.g. the `facets` getter hitting a favorite
 *     whose stored domain doesn't parse) would leave the flag stuck `true`,
 *     silencing every subsequent `_notify()` until a full reload;
 *   - hardcoding `false` on exit would prematurely unblock when the window is
 *     nested inside another blocked window (e.g. splitAndAddDomain calling
 *     createNewGroupBy). Restoring the captured value keeps nesting correct.
 *
 * Sibling helpers in this search layer (notably search_split_domain.js, which
 * open-codes the same try/finally) should adopt this helper too.
 *
 * @param {SearchModel} searchModel
 * @param {() => void} fn - synchronous callback run inside the blocked window
 */
export function withNotificationsBlocked(searchModel, fn) {
    const wasBlocked = searchModel.blockNotification;
    searchModel.blockNotification = true;
    try {
        fn();
    } finally {
        searchModel.blockNotification = wasBlocked;
    }
}

/**
 * Create an ir.filters record on the server.
 * @param {SearchModel} searchModel
 * @param {Object} irFilter
 * @returns {Promise<number>}
 */
export async function createIrFilters(searchModel, irFilter) {
    const serverSideIds = await searchModel.orm.call("ir.filters", "create_filter", [
        irFilter,
    ]);
    rpcBus.trigger(RpcEvent.CLEAR_CACHES, "get_views");
    return serverSideIds[0];
}

/**
 * Activate a filter of type 'field' with given searchItemId with
 * autocomplete value, label, and operator.
 * @param {SearchModel} searchModel
 * @param {number} searchItemId
 * @param {Object} autocompleteValue
 */
export function addAutoCompletionValues(searchModel, searchItemId, autocompleteValue) {
    const searchItem = searchModel.searchItems[searchItemId];
    if (!["field", "field_property"].includes(searchItem.type)) {
        return;
    }
    const { label, value, operator } = autocompleteValue;
    const queryElem = searchModel.query.find(
        (queryElem) =>
            queryElem.searchItemId === searchItemId &&
            "autocompleteValue" in queryElem &&
            queryElem.autocompleteValue.value === value &&
            queryElem.autocompleteValue.operator === operator,
    );
    if (!queryElem) {
        searchModel.query.push({ searchItemId, autocompleteValue });
    } else {
        queryElem.autocompleteValue.label = label;
    }
    searchModel._notify();
}

/**
 * Remove all query elements.
 * @param {SearchModel} searchModel
 */
export function clearQuery(searchModel) {
    searchModel.query = [];
    searchModel.orderByCount = false;
    searchModel._notify();
}

/**
 * Remove filter, field and favorite facets but keep groupBy ones.
 * @param {SearchModel} searchModel
 */
export function clearFilters(searchModel) {
    // The `facets` getter runs inside this window and can throw on a favorite
    // whose stored domain doesn't parse; withNotificationsBlocked guarantees the
    // flag is reset so a throw can't permanently silence the model.
    withNotificationsBlocked(searchModel, () => {
        searchModel.facets.forEach((facet) => {
            if (facet.type !== "groupBy") {
                searchModel.deactivateGroup(facet.groupId);
            }
        });
    });
    searchModel._notify();
}

/**
 * Create a new filter of type 'favorite' and activate it.
 * @param {SearchModel} searchModel
 * @param {Object} params
 * @returns {Promise<number>}
 */
export async function createNewFavorite(searchModel, params) {
    const { preFavorite, irFilter } = searchModel._getIrFilterDescription(params);
    const serverSideId = await searchModel._createIrFilters(irFilter);

    withNotificationsBlocked(searchModel, () => {
        searchModel.clearQuery();
        const favorite = {
            ...preFavorite,
            type: "favorite",
            id: searchModel.nextId,
            groupId: searchModel.nextGroupId,
            groupNumber:
                preFavorite.userIds.length === 1
                    ? FAVORITE_PRIVATE_GROUP
                    : FAVORITE_SHARED_GROUP,
            removable: true,
            serverSideId,
        };
        searchModel.searchItems[searchModel.nextId] = favorite;
        searchModel.query.push({ searchItemId: searchModel.nextId });
        searchModel.nextGroupId++;
        searchModel.nextId++;
    });
    searchModel._notify();
    return serverSideId;
}

/**
 * Create new search items of type 'filter' and activate them.
 * @param {SearchModel} searchModel
 * @param {Object[]} prefilters
 * @returns {number[]}
 */
export function createNewFilters(searchModel, prefilters) {
    if (!prefilters.length) {
        return [];
    }
    prefilters.forEach((preFilter) => {
        // Copy rather than Object.assign onto the caller's prefilter — this is
        // public API (search_model.createNewFilters); stamping id/groupId/type
        // onto the passed-in object would corrupt any reused prefilter template.
        const filter = {
            ...preFilter,
            groupId: searchModel.nextGroupId,
            groupNumber: searchModel.nextGroupNumber,
            id: searchModel.nextId,
            type: "filter",
        };
        searchModel.searchItems[searchModel.nextId] = filter;
        searchModel.query.push({ searchItemId: searchModel.nextId });
        searchModel.nextId++;
    });
    searchModel.nextGroupId++;
    searchModel.nextGroupNumber++;
    searchModel._notify();
}

/**
 * Create a new filter of type 'groupBy' or 'dateGroupBy' and activate it.
 * @param {SearchModel} searchModel
 * @param {string} fieldName
 * @param {Object} [options]
 * @param {string} [options.interval]
 * @param {boolean} [options.invisible]
 */
export function createNewGroupBy(searchModel, fieldName, { interval, invisible } = {}) {
    const field = searchModel.searchViewFields[fieldName];
    const { string, type: fieldType } = field;
    const firstGroupBy = Object.values(searchModel.searchItems).find(
        (f) => f.type === "groupBy",
    );
    const preSearchItem = {
        description: string || fieldName,
        fieldName,
        fieldType,
        groupId: firstGroupBy ? firstGroupBy.groupId : searchModel.nextGroupId++,
        groupNumber: searchModel.nextGroupNumber,
        id: searchModel.nextId,
        custom: true,
    };
    if (invisible) {
        preSearchItem.invisible = "True";
    }
    // toggleDateGroupBy/toggleSearchItem each end with their own _notify(); block
    // notifications around the toggle so the trailing _notify() below is the only
    // reload — otherwise "Add Custom Group" triggers two full reloads.
    withNotificationsBlocked(searchModel, () => {
        if (["date", "datetime"].includes(fieldType)) {
            searchModel.searchItems[searchModel.nextId] = Object.assign(
                {
                    type: "dateGroupBy",
                    defaultIntervalId: interval || DEFAULT_INTERVAL,
                },
                preSearchItem,
            );
            searchModel.toggleDateGroupBy(searchModel.nextId);
        } else {
            searchModel.searchItems[searchModel.nextId] = Object.assign(
                { type: "groupBy" },
                preSearchItem,
            );
            searchModel.toggleSearchItem(searchModel.nextId);
        }
        searchModel.nextGroupNumber++;
        searchModel.nextId++;
    });
    searchModel._notify();
}

/**
 * Deactivate a group, i.e. delete the query elements with given groupId.
 * @param {SearchModel} searchModel
 * @param {number|symbol} groupId
 */
export function deactivateGroup(searchModel, groupId) {
    if (groupId === SPECIAL) {
        delete searchModel.defaultGroupBy;
        searchModel._notify();
        return;
    }
    searchModel.query = searchModel.query.filter((queryElem) => {
        const searchItem = searchModel.searchItems[queryElem.searchItemId];
        return searchItem.groupId !== groupId;
    });
    checkOrderByCountStatus(searchModel);
    searchModel._notify();
}

/**
 * Toggle a simple filter on or off.
 * @param {SearchModel} searchModel
 * @param {number} searchItemId
 */
export function toggleSearchItem(searchModel, searchItemId) {
    const searchItem = searchModel.searchItems[searchItemId];
    if (searchItem.isInvalid) {
        return;
    }
    switch (searchItem.type) {
        case "dateFilter":
        case "dateGroupBy":
        case "field_property":
        case "field": {
            return;
        }
    }
    const index = searchModel.query.findIndex(
        (queryElem) => queryElem.searchItemId === searchItemId,
    );
    if (index >= 0) {
        searchModel.query.splice(index, 1);
        checkOrderByCountStatus(searchModel);
    } else {
        if (searchItem.type === "favorite") {
            // Clearing the query must also reset orderByCount (as clearQuery
            // does): a favorite carrying group_by would otherwise load with a
            // stale {name:"__count"} sort it never contained, because
            // computeOrderBy injects it whenever groupBy.length && orderByCount.
            searchModel.query = [];
            searchModel.orderByCount = false;
        }
        searchModel.query.push({ searchItemId });
    }
    searchModel._notify();
}

/**
 * Toggle a date filter query element.
 * @param {SearchModel} searchModel
 * @param {number} searchItemId
 * @param {string} [generatorId]
 */
export function toggleDateFilter(searchModel, searchItemId, generatorId) {
    const searchItem = searchModel.searchItems[searchItemId];
    if (searchItem.type !== "dateFilter") {
        return;
    }
    let generatorIds = generatorId ? [generatorId] : searchItem.defaultGeneratorIds;
    // defaultGeneratorIds come unvalidated from arch/context strings
    // (`default_period="..."`, `search_default_x="..."`). An unknown id used
    // to slip into the query and silently produce an ACTIVE filter with an
    // empty facet and a match-all domain — drop it loudly instead. Skip the
    // check when the item carries no optionsParams (nothing to validate
    // against — getPeriodOptions destructures it): e.g. a directly-toggled
    // explicit generatorId, or a bare searchItem in unit tests.
    if (searchItem.optionsParams) {
        const knownOptions = getPeriodOptions(
            searchModel.referenceMoment,
            searchItem.optionsParams,
        );
        const validGeneratorIds = generatorIds.filter(
            (gid) => gid.startsWith("custom") || knownOptions.some((o) => o.id === gid),
        );
        if (validGeneratorIds.length !== generatorIds.length) {
            console.warn(
                `[search] unknown period generator id(s) on filter "${searchItem.name}":`,
                generatorIds.filter((gid) => !validGeneratorIds.includes(gid)),
            );
        }
        generatorIds = validGeneratorIds;
    }
    for (const generatorId of generatorIds) {
        const index = searchModel.query.findIndex(
            (queryElem) =>
                queryElem.searchItemId === searchItemId &&
                "generatorId" in queryElem &&
                queryElem.generatorId === generatorId,
        );
        if (index >= 0) {
            searchModel.query.splice(index, 1);
            if (!yearSelected(searchModel._getSelectedGeneratorIds(searchItemId))) {
                searchModel.query = searchModel.query.filter(
                    (queryElem) => queryElem.searchItemId !== searchItemId,
                );
            }
        } else {
            if (generatorId.startsWith("custom")) {
                searchModel.query = searchModel.query.filter(
                    (queryElem) => searchItemId !== queryElem.searchItemId,
                );
                searchModel.query.push({ searchItemId, generatorId });
                continue;
            }
            searchModel.query = searchModel.query.filter(
                (queryElem) =>
                    queryElem.searchItemId !== searchItemId ||
                    !queryElem.generatorId.startsWith("custom"),
            );
            searchModel.query.push({ searchItemId, generatorId });
            if (!yearSelected(searchModel._getSelectedGeneratorIds(searchItemId))) {
                const periodOption = getPeriodOptions(
                    searchModel.referenceMoment,
                    searchItem.optionsParams,
                ).find((o) => o.id === generatorId);
                if (!periodOption) {
                    break;
                }
                const { defaultYearId } = periodOption;
                searchModel.query.push({
                    searchItemId,
                    generatorId: defaultYearId,
                });
            }
        }
    }
    searchModel._notify();
}

/**
 * Toggle a date groupBy interval.
 * @param {SearchModel} searchModel
 * @param {number} searchItemId
 * @param {string} [intervalId]
 */
export function toggleDateGroupBy(searchModel, searchItemId, intervalId) {
    const searchItem = searchModel.searchItems[searchItemId];
    if (searchItem.type !== "dateGroupBy") {
        return;
    }
    intervalId = intervalId || searchItem.defaultIntervalId;
    const index = searchModel.query.findIndex(
        (queryElem) =>
            queryElem.searchItemId === searchItemId &&
            "intervalId" in queryElem &&
            queryElem.intervalId === intervalId,
    );
    if (index >= 0) {
        searchModel.query.splice(index, 1);
        checkOrderByCountStatus(searchModel);
    } else {
        searchModel.query.push({ searchItemId, intervalId });
    }
    searchModel._notify();
}

/**
 * Open the custom filter dialog (DomainSelectorDialog).
 * @param {SearchModel} searchModel
 */
export async function spawnCustomFilterDialog(searchModel) {
    const domain = searchModel.getDefaultDomain(searchModel.searchViewFields);
    searchModel.dialog.add(searchModel.DomainSelectorDialog, {
        resModel: searchModel.resModel,
        defaultConnector: "|",
        domain,
        context: searchModel.globalContext,
        onConfirm: (domain) => searchModel.splitAndAddDomain(domain),
        disableConfirmButton: (domain) => domain === `[]`,
        title: _t("Custom Filter"),
        confirmButtonText: _t("Search"),
        discardButtonText: _t("Discard"),
        isDebugMode: searchModel.isDebugMode,
    });
}

/**
 * Toggle groupBy sort direction between Desc/Asc.
 * @param {SearchModel} searchModel
 */
export function switchGroupBySort(searchModel) {
    if (searchModel.orderByCount === "Desc") {
        searchModel.orderByCount = "Asc";
    } else {
        searchModel.orderByCount = "Desc";
    }
    searchModel._notify();
}
