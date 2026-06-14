// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_dedup - Shares a single promise across identical concurrent RPC requests */

/**
 * RPC deduplication wrapper.
 *
 * When multiple components simultaneously request the same data (e.g.,
 * `orm.read("res.partner", [1])` from both a form and a sidebar), separate
 * RPCs are fired. This wrapper ensures identical in-flight requests share
 * a single RPC promise.
 *
 * This is a pure utility with no OWL or DOM dependencies.
 *
 * @see rpc.js for the integration point
 */

/**
 * Wrap an RPC function to deduplicate identical concurrent requests.
 *
 * While a request for a given (url, params) pair is in flight, subsequent
 * calls with the same signature return the same promise. Once the request
 * settles (success or failure), the entry is removed so future calls
 * trigger a fresh RPC.
 *
 * @template T
 * @param {(url: string, params: any) => Promise<T>} rpcFn - The original RPC function.
 * @returns {(url: string, params: any) => Promise<T>} A deduplicating wrapper.
 */
export function deduplicateRpc(rpcFn) {
    /** @type {Map<string, Promise<T>>} */
    const inflight = new Map();

    return function dedupRpc(url, params) {
        const key = buildKey(url, params);

        const existing = inflight.get(key);
        if (existing) {
            return existing;
        }

        const promise = rpcFn(url, params).finally(() => {
            inflight.delete(key);
        });

        inflight.set(key, promise);
        return promise;
    };
}

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
export function stableStringify(value) {
    if (value && typeof value.toJSON === "function") {
        value = value.toJSON();
    }
    if (value === undefined || typeof value === "function" || typeof value === "symbol") {
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
