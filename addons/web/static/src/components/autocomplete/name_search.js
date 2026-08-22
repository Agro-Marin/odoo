// @ts-check
/** @odoo-module native */

import { _t } from "@web/core/translation";

export const SEARCH_LIMIT = 7;

export const SEARCH_MORE_LIMIT = 320;

/**
 * @param {import("@web/core/network/orm_service").ORM} orm
 * @param {string} resModel
 * @param {Object} params
 * @param {string} params.name
 * @param {any[]} params.domain
 * @param {number} params.limit
 * @param {Object} [params.context]
 * @param {string} [params.operator]
 * @param {Object} [params.specification]
 * @returns {Promise<Array<Record<string, any>>>}
 */
export function webNameSearch(
    orm,
    resModel,
    {
        name,
        domain,
        limit,
        context = {},
        operator = "ilike",
        specification = { display_name: {} },
    },
) {
    return orm.call(resModel, "web_name_search", [], {
        name,
        operator,
        domain,
        limit,
        context,
        specification,
    });
}

/**
 * @template T
 * @param {T[]} records
 * @param {number} limit
 * @returns {{ records: T[], hasMore: boolean }}
 */
export function splitOverflow(records, limit) {
    if (records.length > limit) {
        return { records: records.slice(0, limit), hasMore: true };
    }
    return { records, hasMore: false };
}

/**
 * @param {string} name
 * @param {number[]} ids
 * @param {string} [operator]
 * @returns {{ description: string, domain: any[] }}
 */
export function quickSearchFilter(name, ids, operator = "in") {
    return {
        description: _t("Quick search: %s", name),
        domain: [["id", operator, ids]],
    };
}

/**
 * @param {string} [fieldString]
 * @returns {string}
 */
export function searchMoreTitle(fieldString) {
    if (fieldString && fieldString.trim()) {
        return _t("Search: %s", fieldString);
    }
    return _t("Search");
}

/**
 * @returns {string}
 */
export function searchMoreLabel() {
    return _t("Search more...");
}

/**
 * @param {number | number[]} resId
 * @returns {number[]}
 */
export function normalizeSelectedIds(resId) {
    return Array.isArray(resId) ? resId : [resId];
}
