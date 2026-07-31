// @ts-check
/** @odoo-module native */

/**
 * @module @web/core/utils/format/digits
 */

/**
 * @param {{ attrs: Record<string, any>, options: Record<string, any> }} params
 * @returns {number[] | undefined}
 */
export function extractDigits({ attrs, options }) {
    if (attrs.digits) {
        try {
            return JSON.parse(attrs.digits);
        } catch {
            // render; fall through to the option/undefined path.
        }
    }
    if (options.digits) {
        return options.digits;
    }
    return undefined;
}
