// @ts-check
/** @odoo-module native */

/**
 * @param {import("@web/model/relational_model/record").RelationalRecord} record
 * @param {string | undefined} colorField
 * @returns {string}
 */
export function badgeColorClass(record, colorField) {
    const data = /** @type {Record<string, any>} */ (record.data);
    if (colorField && Number.isInteger(data[colorField])) {
        return `o_badge_color_${data[colorField]}`;
    }
    return "";
}
