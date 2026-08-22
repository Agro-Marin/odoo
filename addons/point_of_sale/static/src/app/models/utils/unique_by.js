/** @odoo-module native */
export function uniqueBy(array, agg) {
    const map = new Map();
    for (const item of array) {
        const key = agg(item);
        if (!map.has(key)) {
            map.set(key, item);
        }
    }
    return [...map.values()];
}
