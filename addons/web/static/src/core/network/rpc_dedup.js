// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_dedup - Stable key builder for RPC dedup/cache (buildKey) */

/**
 * JSON-stringify with object keys serialized in sorted order at every depth.
 *
 * ``JSON.stringify`` preserves insertion order, so two semantically identical
 * params objects assembled by different call sites (most commonly a
 * ``context`` built in a different key order) would produce different keys —
 * a silent dedup/cache miss. Sorting keys makes the key a function of the
 * VALUE, not of how the object was built.
 *
 * Mirrors ``JSON.stringify`` semantics for the RPC payload domain: honors
 * ``toJSON()``, omits object entries whose serialization is undefined
 * (undefined/function values), and encodes such array slots as ``null``.
 * RPC params are plain JSON-serializable data by contract, so cycles and
 * BigInt are programming errors and intentionally not special-cased.
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
