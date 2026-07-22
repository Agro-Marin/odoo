// @ts-check
/** @odoo-module native */

/** @module search/search_favorites - Favorites/ir.filters utilities for SearchModel */

/** @import { OrderTerm } from "@web/core/utils/order_by" */

import { makeContext } from "@web/core/context";
import { Domain } from "@web/core/domain";
import { evaluateExpr } from "@web/core/py_js/py";
import { user } from "@web/services/user";

import { FAVORITE_PRIVATE_GROUP, FAVORITE_SHARED_GROUP } from "./search_state.js";

/**
 * Convert an ir.filter record to a favorite search item.
 *
 * @param {Object} irFilter
 * @param {Object} [fields=null] search-model field metadata
 *  (``searchViewFields``). When provided (and non-empty), ``group_by``
 *  entries naming unknown fields are screened out (see below); when absent,
 *  group-bys are imported as-is.
 * @returns {Object} favorite search item (pre-group format)
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
        // Screen out group-bys naming fields that no longer exist: the stored
        // ``group_by`` list is applied with no validation downstream, and the
        // server keeps web_read_group strict — a shared default favorite
        // grouping by a since-removed field 500s the whole view for everyone
        // on load. Screening only here keeps arch-defined groupbys untouched.
        // A ``field:granularity`` entry is validated on its field part, and a
        // ``propertiesField.propName`` entry (property group-by) on its
        // properties parent field.
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
    // JSON.parse returns non-arrays without throwing (e.g. `false` for a NULL
    // column read); quarantine those like an unparseable blob instead of
    // crashing on sort.map below. Also validate the *elements*: a `[null]` /
    // `[123]` (slipped in via migration, import, or raw SQL) is an array, so it
    // passes Array.isArray, then `order.trim()` below throws a TypeError that
    // escapes load() and takes down the whole search view for every user of a
    // shared/default filter.
    if (!Array.isArray(sort) || sort.some((s) => typeof s !== "string")) {
        isInvalid = true;
        sort = [];
    }
    // Validate the stored domain up front: Domain.or([...favorite.domain]) in
    // facet building throws on an unparseable domain inside a notifications-
    // blocked window, poisoning the whole search model — mark invalid instead
    // (toggleSearchItem then skips it). Skip empty/falsy domains though: they're
    // a valid match-all (ir.filters uses domain: "" for context-only favorites)
    // and `new Domain("")` itself throws.
    if (irFilter.domain) {
        try {
            new Domain(irFilter.domain);
        } catch {
            isInvalid = true;
        }
    }
    const orderBy = sort.map((order) => {
        let fieldName;
        let asc;
        // Tolerate extra/irregular whitespace and case: a `sort` written
        // server-side or by another client as "name ASC" / "name  DESC" must
        // parse correctly. Direction is descending only on an explicit "desc"
        // (case-insensitive); anything else (incl. "asc", "ASC", or omitted) is
        // ascending.
        const trimmed = order.trim();
        const sqlNotation = trimmed.split(/\s+/);
        if (sqlNotation.length > 1) {
            fieldName = sqlNotation[0];
            asc = sqlNotation[1].toLowerCase() !== "desc";
        } else {
            fieldName = trimmed[0] === "-" ? trimmed.slice(1) : trimmed;
            asc = trimmed[0] !== "-";
        }
        return { asc, name: fieldName };
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
 * Reconciliate existing search items of type "favorite" with the current ir.filters.
 * Updates changed favorites, removes deleted ones, and creates new ones.
 *
 * @param {Object} searchItems - mutable searchItems map
 * @param {Object[]} query - mutable query array
 * @param {Object[]} irFilters
 * @param {Function} irFilterToFavoriteFn - conversion function (irFilter) => favorite
 * @param {Function} createGroupOfFavoritesFn - (irFilters) => void
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
            // Replace rather than merge: merging cannot remove stale keys
            // (e.g. `isDefault` on a favorite un-defaulted server-side, which
            // irFilterToFavorite only sets when truthy). Keep the identity
            // keys assigned at creation time.
            const { id, groupId } = item;
            const replacement = Object.assign(irFilterToFavoriteFn(irFilter), {
                id,
                groupId,
            });
            searchItems[id] = replacement;
            delete mapping[item.serverSideId];
            // If the reloaded copy is now invalid (domain/sort broken
            // server-side since this favorite was activated), drop it from the
            // query. `toggleSearchItem` refuses to activate an invalid favorite,
            // so leaving an already-active one in place would be the one way an
            // invalid favorite drives a domain build — `computeSearchItemDomain`
            // returns its raw bad domain string and `new Domain(...)` throws,
            // poisoning the whole search model on the next facet/domain access.
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
 * Build the ir.filter description for saving a favorite.
 *
 * @param {Object} params
 * @param {string} params.description
 * @param {boolean} params.isDefault
 * @param {boolean} params.isShared
 * @param {number|false} [params.embeddedActionId]
 * @param {Object} params.localContext - context from env.__getContext__
 * @param {OrderTerm[]} [params.localOrderBy] - orderBy from env.__getOrderBy__
 * @param {Function} params.getContext - () => searchContext
 * @param {Function} params.getDomain - () => Domain (raw, no global)
 * @param {Function} params.getGroupBy - () => string[]
 * @param {Function} params.getOrderBy - () => OrderTerm[]
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
        // The search context is seeded with the whole user context
        // (computeSearchContext), so keys carrying the user-context VALUE are
        // stripped before saving. A user-context key NAME with a DIFFERENT
        // value is an intentional override (e.g. a filter with
        // context="{'lang': 'en_US'}" while the user's lang differs) and must
        // survive into the ir.filters record — deleting on name alone
        // silently dropped it. Strict equality is enough for the seeded case:
        // seeding copies primitive values and nested references as-is.
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
        // group_by LAST so the computed group-by list wins: a residual
        // `group_by` key left inside the composed search context (e.g. from a
        // raw `<filter context="{'group_by': ...}">` whose field was
        // group-restricted and kept as raw context by the arch parser) must not
        // clobber it.
        context: { ...context, group_by: groupBys },
    };

    return { preFavorite, irFilter };
}
