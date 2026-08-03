// @ts-check
/** @odoo-module native */

/** @module search/search_favorites */

/** @import { OrderTerm } from "@web/core/utils/order_by" */

import { makeContext } from "@web/core/context";
import { Domain } from "@web/core/domain";
import { evaluateExpr } from "@web/core/py_js/py";
import { user } from "@web/core/user";

import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP } from "./search_state.js";

/**
 * @param {Object} irFilter
 * @param {Object} [fields=null]
 * @returns {Object}
 */
export function irFilterToFavorite(irFilter, fields = null) {
    const userIds = irFilter.user_ids;
    const groupNumber =
        userIds.length === 1 ? FAVORITE_PRIVATE_GROUP : FAVORITE_SHARED_GROUP;
    let context;
    let isInvalid = false;
    try {
        context = evaluateExpr(irFilter.context, user.context);
    } catch {
        context = {};
        isInvalid = true;
    }
    let groupBys = [];
    if (context.group_by) {
        groupBys = Array.isArray(context.group_by)
            ? context.group_by
            : [context.group_by];
        delete context.group_by;
        if (fields && Object.keys(fields).length) {
            groupBys = groupBys.filter((groupBy) => {
                const fieldName = String(groupBy).split(":")[0];
                const baseName = fieldName.split(".")[0];
                const field = fields[baseName];
                const isValid =
                    !!field && (baseName === fieldName || field.type === "properties");
                if (!isValid) {
                    console.warn(
                        `Favorite "${irFilter.name}": dropping group_by "${groupBy}" — unknown field "${baseName}"`,
                    );
                }
                return isValid;
            });
        }
    }
    let sort;
    try {
        sort = JSON.parse(irFilter.sort);
    } catch {
        isInvalid = true;
        sort = [];
    }
    if (!Array.isArray(sort) || sort.some((s) => typeof s !== "string")) {
        isInvalid = true;
        sort = [];
    }
    if (irFilter.domain) {
        try {
            new Domain(irFilter.domain);
        } catch {
            isInvalid = true;
        }
    }
    const orderBy = sort.flatMap((order) => {
        let fieldName;
        let asc;
        const trimmed = order.trim();
        const sqlNotation = trimmed.split(/\s+/);
        if (sqlNotation.length > 1) {
            fieldName = sqlNotation[0];
            asc = sqlNotation[1].toLowerCase() !== "desc";
        } else {
            fieldName = trimmed.startsWith("-") ? trimmed.slice(1) : trimmed;
            asc = !trimmed.startsWith("-");
        }
        if (!fieldName) {
            isInvalid = true;
            return [];
        }
        return [{ asc, name: fieldName }];
    });
    const favorite = {
        context,
        description: irFilter.name,
        domain: irFilter.domain,
        groupBys,
        groupNumber,
        orderBy,
        removable: true,
        serverSideId: irFilter.id,
        type: "favorite",
        userIds,
        isInvalid,
    };
    if (irFilter.is_default && !isInvalid) {
        favorite.isDefault = irFilter.is_default;
    }
    return favorite;
}

/**
 * @param {Object} searchItems
 * @param {Object[]} query
 * @param {Object[]} irFilters
 * @param {Function} irFilterToFavoriteFn
 * @param {Function} createGroupOfFavoritesFn
 */
export function reconciliateFavorites(
    searchItems,
    query,
    irFilters,
    irFilterToFavoriteFn,
    createGroupOfFavoritesFn,
) {
    const filters = irFilters || [];
    const mapping = Object.fromEntries(filters.map((i) => [i.id, i]));
    for (const item of Object.values(searchItems)) {
        if (item.type !== "favorite") {
            continue;
        }
        const irFilter = mapping[item.serverSideId];
        if (irFilter) {
            const { id, groupId } = item;
            const replacement = Object.assign(irFilterToFavoriteFn(irFilter), {
                id,
                groupId,
            });
            searchItems[id] = replacement;
            delete mapping[item.serverSideId];
            if (replacement.isInvalid) {
                const queryIndex = query.findIndex((q) => q.searchItemId === id);
                if (queryIndex !== -1) {
                    query.splice(queryIndex, 1);
                }
            }
        } else {
            const queryIndex = query.findIndex((q) => q.searchItemId === item.id);
            if (queryIndex !== -1) {
                query.splice(queryIndex, 1);
            }
            delete searchItems[item.id];
        }
    }
    createGroupOfFavoritesFn(Object.values(mapping));
}

/**
 * @param {Object} params
 * @param {string} params.description
 * @param {boolean} params.isDefault
 * @param {boolean} params.isShared
 * @param {number|false} [params.embeddedActionId]
 * @param {Object} params.localContext
 * @param {OrderTerm[]} [params.localOrderBy]
 * @param {Function} params.getContext
 * @param {Function} params.getDomain
 * @param {Function} params.getGroupBy
 * @param {Function} params.getOrderBy
 * @param {Object} params.globalContext
 * @param {number} params.actionId
 * @param {string} params.resModel
 * @returns {{ preFavorite: Object, irFilter: Object }}
 */
export function buildIrFilterDescription({
    description,
    isDefault,
    isShared,
    embeddedActionId,
    localContext,
    localOrderBy,
    getContext,
    getDomain,
    getGroupBy,
    getOrderBy,
    globalContext,
    actionId,
    resModel,
}) {
    const context = makeContext([getContext(), localContext]);
    const userContext = user.context;
    for (const key of Object.keys(context)) {
        if (
            (key in userContext && context[key] === userContext[key]) ||
            /^search(panel)?_default_/.test(key)
        ) {
            delete context[key];
        }
    }
    const domain = getDomain().toString();
    const groupBys = getGroupBy();
    const orderBy = localOrderBy || getOrderBy();
    const userIds = isShared ? [] : [user.userId];

    const preFavorite = {
        description,
        isDefault,
        domain,
        context,
        groupBys,
        orderBy,
        userIds,
    };
    const irFilter = {
        name: description,
        action_id: actionId,
        model_id: resModel,
        domain,
        embedded_action_id: embeddedActionId,
        embedded_parent_res_id: globalContext.active_id || false,
        is_default: isDefault,
        sort: JSON.stringify(
            orderBy.map((o) => `${o.name}${o.asc === false ? " desc" : ""}`),
        ),
        user_ids: userIds,
        context: { ...context, group_by: groupBys },
    };

    return { preFavorite, irFilter };
}
