// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/order_by */

/**
 * @typedef {{
 *  name: string;
 *  asc?: boolean;
 * }} OrderTerm
 */

/**
 * @param {OrderTerm[]} orderBy
 * @returns {string}
 */
export function orderByToString(orderBy) {
    return orderBy
        .map((o) => `${o.name} ${o.asc === false ? "DESC" : "ASC"}`)
        .join(", ");
}

export class InvalidOrderError extends Error {
    name = "InvalidOrderError";
}

/**
 * Mirrors the server's own rule (``models._check_qorder``): a comma-separated
 * list of field names, each optionally followed by ``asc`` or ``desc``.
 *
 * Anything else throws rather than being coerced. Silently accepting it used to
 * produce two distinct failures: an empty term round-tripped through
 * ``orderByToString`` as ``" ASC"``, which the server rejects with
 * ``ValueError: Invalid field 'ASC'`` instead of its own readable message; and
 * an unrecognised direction word was read as DESC, so ``"id ASCENDING"``
 * silently reversed the sort the server would have refused outright.
 *
 * @param {string | null | undefined | false} string
 * @return {OrderTerm[]}
 * @throws {InvalidOrderError} on an empty term or an unrecognised direction
 */
export function stringToOrderBy(string) {
    if (!string) {
        return [];
    }
    return string.split(",").map((order) => {
        const term = order.trim();
        const [name, direction, ...extra] = term.split(/\s+/);
        if (!name || extra.length) {
            throw new InvalidOrderError(
                `Invalid order term "${term}" in "${string}": expected a field name optionally followed by "asc" or "desc"`,
            );
        }
        if (direction !== undefined && !/^(asc|desc)$/i.test(direction)) {
            throw new InvalidOrderError(
                `Invalid order direction "${direction}" in "${string}": expected "asc" or "desc"`,
            );
        }
        return {
            name,
            asc: direction === undefined || direction.toLowerCase() === "asc",
        };
    });
}
