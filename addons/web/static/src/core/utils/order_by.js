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
        const [name, direction, ...extra] = order.trim().split(/\s+/);
        if (extra.length) {
            // A term with trailing tokens (`"foo desc nulls last"`) used to
            // fall through to the bare-name branch and come back ASC — the one
            // reading that inverts the caller's stated intent. Nothing in Odoo
            // emits such a term, so this is unreachable rather than a fix for
            // an observed bug; it is here so the unreachable case is loud
            // instead of silently wrong.
            throw new Error(`Invalid order term: "${order.trim()}"`);
        }
        return {
            name,
            asc: direction === undefined || direction.toLowerCase() === "asc",
        };
    });
}
