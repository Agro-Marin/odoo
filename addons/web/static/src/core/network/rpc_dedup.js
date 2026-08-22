// @ts-check
/** @odoo-module native */

/**
 * @param {any} value
 * @returns {string | undefined}
 */
function stableStringify(value, seen = new Set()) {
    if (value && typeof value.toJSON === "function") {
        value = value.toJSON();
    }
    if (
        value === undefined ||
        typeof value === "function" ||
        typeof value === "symbol"
    ) {
        return undefined;
    }
    if (value === null || typeof value !== "object") {
        return JSON.stringify(value);
    }
    if (seen.has(value)) {
        throw new TypeError("buildKey: converting circular structure to a cache key");
    }
    seen.add(value);
    if (Array.isArray(value)) {
        const out = `[${value.map((v) => stableStringify(v, seen) ?? "null").join(",")}]`;
        seen.delete(value);
        return out;
    }
    const parts = [];
    for (const key of Object.keys(value).sort()) {
        const serialized = stableStringify(value[key], seen);
        if (serialized !== undefined) {
            parts.push(`${JSON.stringify(key)}:${serialized}`);
        }
    }
    seen.delete(value);
    return `{${parts.join(",")}}`;
}

/**
 * @param {string} url
 * @param {any} params
 * @returns {string}
 */
export function buildKey(url, params) {
    return /** @type {string} */ (stableStringify({ url, params }));
}
