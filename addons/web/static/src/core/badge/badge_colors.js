// @ts-check
/** @odoo-module native */

/** @module @web/core/badge/badge_colors - Shared badge color-class helper */

/**
 * Compute the `o_badge_color_<n>` class for a record's integer color index.
 *
 * Only emits a color class for a real integer color index. A null/false color
 * field would otherwise produce the junk class `o_badge_color_false`, so the
 * guard returns an empty string and lets callers apply their own fallback.
 *
 * @param {import("@web/model/relational_model/record").Record} record
 * @param {string | undefined} colorField Name of the integer color field, if any.
 * @returns {string} `o_badge_color_<n>` for an integer index, otherwise `""`.
 */
export function badgeColorClass(record, colorField) {
    if (colorField && Number.isInteger(record.data[colorField])) {
        return `o_badge_color_${record.data[colorField]}`;
    }
    return "";
}
