// @ts-check
/** @odoo-module native */

/**
 * @typedef {{
 * name: string;
 * asc?: boolean;
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
 * @param {string | null | undefined | false} string
 * @return {OrderTerm[]}
 * @throws {InvalidOrderError}
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
