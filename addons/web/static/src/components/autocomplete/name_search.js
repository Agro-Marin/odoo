// @ts-check
/** @odoo-module native */

/** @module @web/components/autocomplete/name_search */

/**
 * Shared core of the quick-search flow built on `AutoComplete`:
 * name search -> bounded dropdown -> "Search more..." -> SelectCreateDialog.
 *
 * Two components implement that flow — `RecordAutocomplete`
 * (components/record_selectors) and `Many2XAutocomplete` (fields/relational) —
 * and used to carry private copies of its constants and call shapes, which had
 * already drifted apart (audit U11, proposal 2a). This module owns the pieces
 * that must not diverge:
 *
 *   - the `web_name_search` RPC call shape,
 *   - the dropdown page size and the quick-search fetch bound,
 *   - the overflow probe behind the only-on-overflow "Search more..." rule,
 *   - the "Quick search: %s" dynamic filter and dialog title passed to
 *     `SelectCreateDialog`.
 *
 * Everything else — concurrency policy, create actions, memoization, display
 * name caching — is deliberately left to the components: that is where the two
 * flows genuinely differ.
 */

import { _t } from "@web/core/translation";

/** Records shown in the dropdown before "Search more..." takes over. */
export const SEARCH_LIMIT = 7;

/**
 * Records fetched to build the "Quick search: %s" filter of the
 * "Search more..." dialog.
 */
export const SEARCH_MORE_LIMIT = 320;

/**
 * The quick-search RPC: `web_name_search` on *resModel*.
 *
 * Returns the same `(id, display_name)` pairs as `name_search`, as record
 * dicts shaped by *specification* — the default display-name-only
 * specification adds `__formatted_display_name` to each record.
 *
 * The ORM promise is returned as-is, so callers keep its `abort()`.
 *
 * @param {import("@web/core/network/orm_service").ORM} orm
 * @param {string} resModel
 * @param {Object} params
 * @param {string} params.name the term to search for
 * @param {any[]} params.domain
 * @param {number} params.limit
 * @param {Object} [params.context]
 * @param {string} [params.operator]
 * @param {Object} [params.specification] fields to read on each match
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
 * The overflow probe behind the only-on-overflow "Search more..." rule: fetch
 * `limit + 1` records, then split the result into the page actually shown and
 * the answer to "were there more?". The dropdown offers "Search more..." only
 * when the probe overflowed — never as a constant fixture.
 *
 * @template T
 * @param {T[]} records as returned by a `limit + 1` search
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
 * The "Quick search: %s" dynamic filter shown by the "Search more..." dialog,
 * scoping it to the ids the quick search already found.
 *
 * @param {string} name the searched term, shown in the filter description
 * @param {number[]} ids
 * @param {string} [operator] `"id"`-domain operator, `"in"` unless stated
 * @returns {{ description: string, domain: any[] }}
 */
export function quickSearchFilter(name, ids, operator = "in") {
    return {
        description: _t("Quick search: %s", name),
        domain: [["id", operator, ids]],
    };
}

/**
 * Title of the "Search more..." SelectCreateDialog.
 *
 * @param {string} [fieldString] the field's label, if it has one
 * @returns {string}
 */
export function searchMoreTitle(fieldString) {
    if (fieldString && fieldString.trim()) {
        return _t("Search: %s", fieldString);
    }
    return _t("Search");
}

/**
 * Label of the "Search more..." dropdown option.
 *
 * @returns {string}
 */
export function searchMoreLabel() {
    return _t("Search more...");
}

/**
 * `SelectCreateDialog.onSelected` hands back one id or an array of ids
 * depending on its `multiSelect` flag; both quick-search flows want a list.
 *
 * @param {number | number[]} resId
 * @returns {number[]}
 */
export function normalizeSelectedIds(resId) {
    return Array.isArray(resId) ? resId : [resId];
}
