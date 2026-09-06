// @ts-check
/** @odoo-module native */

/**
 * @typedef {any} PosOrderline
 * @typedef {object} OrderlineGroup
 * @property {PosOrderline[]} lines
 * @property {number} quantity
 * @property {number} displayPrice
 * @property {string[]} lotLines
 * @property {object | undefined} location
 */

/**
 * @param {PosOrderline} line
 * @returns {string}
 */
export function orderlineGroupKey(line) {
    return [
        line.product_id.id,
        line.price_unit,
        line.getDiscount(),
        line.getNote(),
        line.customer_note || "",
        line.location_id?.id ?? 0,
    ].join("|");
}

/**
 * Collapses the repeated lines of one product into one displayed line.
 *
 * Lines sharing product, unit price, discount, notes and stock location form a
 * group; combos and their children pass through untouched. The displayed member
 * of a group is the selected line when one is selected, otherwise the first, so
 * the numpad and the lot icon keep acting on the line the cashier picked.
 *
 * @param {PosOrderline[]} lines display-ordered lines, combo children behind their parent
 * @returns {{ lines: PosOrderline[], groupOf: Map<string, OrderlineGroup> }}
 */
export function groupOrderlines(lines) {
    /** @type {PosOrderline[]} */
    const displayed = [];
    /** @type {Map<string, OrderlineGroup>} */
    const groupOf = new Map();
    /** @type {Map<string, OrderlineGroup>} */
    const groupByKey = new Map();

    for (const line of lines) {
        if (line.isPartOfCombo()) {
            displayed.push(line);
            continue;
        }
        const key = orderlineGroupKey(line);
        let group = groupByKey.get(key);
        if (!group) {
            group = {
                lines: [],
                quantity: 0,
                displayPrice: 0,
                lotLines: [],
                location: line.location_id,
            };
            groupByKey.set(key, group);
            displayed.push(line);
        }
        group.lines.push(line);
        group.quantity += line.getQuantity();
        group.displayPrice += line.displayPrice;
        group.lotLines.push(...line.packLotLines);
    }

    for (const group of groupByKey.values()) {
        const representative =
            group.lines.find((line) => line.isSelected()) || group.lines[0];
        displayed[displayed.indexOf(group.lines[0])] = representative;
        groupOf.set(representative.uuid, group);
    }
    return { lines: displayed, groupOf };
}
