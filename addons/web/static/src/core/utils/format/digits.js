// @ts-check
/** @odoo-module native */

/**
 * @param {unknown} value
 * @returns {value is number[]}
 */
function isDigitsPair(value) {
    return (
        Array.isArray(value) &&
        value.length === 2 &&
        value.every((n) => typeof n === "number" && Number.isFinite(n))
    );
}

/**
 * @param {{ attrs: Record<string, any>, options: Record<string, any> }} params
 * @returns {number[] | undefined}
 */
export function extractDigits({ attrs, options }) {
    if (attrs.digits) {
        try {
            const parsed = JSON.parse(attrs.digits);
            if (isDigitsPair(parsed)) {
                return parsed;
            }
        } catch {}
    }
    if (isDigitsPair(options.digits)) {
        return options.digits;
    }
    return undefined;
}
