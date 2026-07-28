// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/order_by - Converts between OrderTerm arrays and SQL-like "field ASC/DESC" strings */

/**
 * @typedef {{
 *  name: string;
 *  asc?: boolean;
 * }} OrderTerm
 */

/**
 * An omitted ``asc`` means ASCENDING, matching every other reader and writer of
 * an order term: {@link stringToOrderBy} parses a bare ``"foo"`` as
 * ``{ name: "foo", asc: true }``, ``search_favorites`` serializes with
 * ``o.asc === false ? " desc" : ""``, and SQL's own default is ASC. This used
 * to test ``o.asc`` for truthiness, so a term built without the optional field
 * serialized as DESC and a round trip through ``stringToOrderBy`` flipped the
 * sort direction.
 *
 * @param {OrderTerm[]} orderBy
 * @returns {string}
 */
export function orderByToString(orderBy) {
    return orderBy
        .map((o) => `${o.name} ${o.asc === false ? "DESC" : "ASC"}`)
        .join(", ");
}

/**
 * @param {string | null | undefined | false} string
 * @return {OrderTerm[]}
 */
export function stringToOrderBy(string) {
    if (!string) {
        return [];
    }
    return string.split(",").map((order) => {
        const splitOrder = order.trim().split(/\s+/);
        if (splitOrder.length === 2) {
            return {
                name: splitOrder[0],
                asc: splitOrder[1].toLowerCase() === "asc",
            };
        } else {
            return {
                name: splitOrder[0],
                asc: true,
            };
        }
    });
}
