// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_dedup - Stable key builder for RPC dedup/cache (buildKey) */

/**
 * JSON.stringify with keys sorted at every depth, so two semantically
 * identical params objects (e.g. a ``context`` built in a different key
 * order) hash the same instead of causing a silent dedup/cache miss.
 * Honors ``toJSON()``; cycles/BigInt are programming errors, not special-cased.
 *
 * @param {any} value
 * @returns {string | undefined}
 */
function stableStringify(value) {
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
    if (Array.isArray(value)) {
        return `[${value.map((v) => stableStringify(v) ?? "null").join(",")}]`;
    }
    const parts = [];
    for (const key of Object.keys(value).sort()) {
        const serialized = stableStringify(value[key]);
        if (serialized !== undefined) {
            parts.push(`${JSON.stringify(key)}:${serialized}`);
        }
    }
    return `{${parts.join(",")}}`;
}

/**
 * Build a deduplication/cache key from URL and params.
 *
 * Key-order independent: see {@link stableStringify}. Also used by the RPC
 * cache layer (rpc.js) so both layers share one key space.
 *
 * @param {string} url
 * @param {any} params
 * @returns {string}
 */
export function buildKey(url, params) {
    return /** @type {string} */ (stableStringify({ url, params }));
}
