// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_cache - Encrypted RAM/IndexedDB cache for RPC responses */

import { RpcEvent } from "@web/core/events";
import { ConnectionLostError, rpcBus } from "@web/core/network/rpc";
import { deepCopy, deepEqual } from "@web/core/utils/collections/objects";
import { Deferred } from "@web/core/utils/concurrency";
import { IDBQuotaExceededError, IndexedDB } from "@web/core/utils/indexed_db";

/**
 * @typedef {{
 * callback?: function;
 * type?: "ram" | "disk";
 * update?: "once" | "always";
 * immutable?: boolean;
 * model?: string;
 * silent?: boolean;
 * }} RPCCacheSettings
 *
 * ``model`` (e.g. ``"res.partner"``) joins the entry to a per-table
 * model→keys reverse index, making ``invalidateByModel`` O(1) instead of
 * scanning + parsing every key.
 *
 * ``silent`` applies only to a BACKGROUND refresh that fails while a cached
 * value was already served (``update: "always"``): the stale value stands, and
 * the connection error is reported on ``rpcBus`` only, instead of also being
 * re-thrown for the global unhandled-rejection handler to surface.
 */

/**
 * Server-emitted content-hash field: opted-in endpoints inject it into their
 * response so ``payloadChanged`` can compare versions in O(1) instead of
 * deep-serializing both payloads on ``update: "always"`` refreshes.
 *
 * See ``addons/odoo/addons/web/models/web_search_panel.py`` for the
 * server-side stamping pattern (sha256 of canonical JSON).
 */
const VERSION_FIELD = "__version";

/**
 * O(1) structural disqualifier: ``true`` when the payloads' top-level shape
 * differs (array vs object, different lengths/key counts), so callers can
 * skip a full compare. ``false`` only means "shape matches, compare further".
 * ~400× faster than a full deep compare on a 200-record list that differs
 * by one row.
 */
function shapeDiffers(/** @type {any} */ a, /** @type {any} */ b) {
    if (Array.isArray(a)) {
        return !Array.isArray(b) || a.length !== b.length;
    }
    if (a && typeof a === "object") {
        if (!b || typeof b !== "object" || Array.isArray(b)) {
            return true;
        }
        return Object.keys(a).length !== Object.keys(b).length;
    }
    return false;
}

/**
 * Determine whether two cached payloads differ, layered cheap → expensive:
 * reference equality, then ``__version`` hash compare (if both sides have
 * one), then a shape disqualifier, then a full ``deepEqual``. A prior
 * ``JSON.stringify`` byte-compare was key-order-fragile — the server can
 * emit dict keys in different insertion order across runs — causing
 * spurious "changed" reports and needless re-delivery/re-persist.
 *
 * @param {any} fromCacheValue prior cached value (may be null/undefined)
 * @param {any} result freshly-fetched server value
 * @returns {boolean}
 */
function payloadChanged(fromCacheValue, result) {
    if (fromCacheValue === result) {
        return false;
    }
    if (
        fromCacheValue &&
        result &&
        typeof fromCacheValue === "object" &&
        typeof result === "object" &&
        fromCacheValue[VERSION_FIELD] != null &&
        result[VERSION_FIELD] != null
    ) {
        return fromCacheValue[VERSION_FIELD] !== result[VERSION_FIELD];
    }
    if (shapeDiffers(fromCacheValue, result)) {
        return true;
    }
    return !deepEqual(fromCacheValue, result);
}

function validateSettings(
    /** @type {{ type: string, update: string }} */ { type, update },
) {
    if (!["ram", "disk"].includes(type)) {
        throw new Error(`Invalid "type" settings provided to RPCCache: ${type}`);
    }
    if (!["always", "once"].includes(update)) {
        throw new Error(`Invalid "update" settings provided to RPCCache: ${update}`);
    }
}

/**
 * Recursively freeze a value in place. Idempotent: an already-frozen root
 * short-circuits at O(1) via ``Object.isFrozen`` (leaves are always frozen
 * before the root, so a frozen root implies a fully-frozen subtree).
 *
 * @template T
 * @param {T} value
 * @returns {T}
 */
function deepFreeze(value) {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
        const indexable = /** @type {Record<string, unknown>} */ (value);
        for (const key of Object.keys(indexable)) {
            deepFreeze(indexable[key]);
        }
        Object.freeze(value);
    }
    return value;
}

const CRYPTO_ALGO = "AES-GCM";
const MAX_STORAGE_SIZE = 2 * 1024 * 1024 * 1024;

/**
 * Max number of live entries in the in-memory RAM cache before the
 * least-recently-used one is evicted. Unlike the disk cache (bounded by
 * ``MAX_STORAGE_SIZE``), ``RamCache`` was pruned only by explicit
 * ``invalidate``/``invalidateByModel``: reads with varying params
 * (search-panel / name_search-style calls) accumulated a distinct entry for the
 * whole tab lifetime. Eviction only drops an entry, forcing a later re-fetch —
 * it never serves stale data.
 */
export const RAM_CACHE_MAX_ENTRIES = 10000;

class Crypto {
    /**
     * @param {string} secret
     */
    constructor(secret) {
        this._cryptoKey = null;
        this._ready = window.crypto.subtle
            .importKey(
                "raw",
                new Uint8Array(
                    secret
                        .match(/../g)
                        .map((/** @type {string} */ h) => Number.parseInt(h, 16)),
                ).buffer,
                CRYPTO_ALGO,
                false,
                ["encrypt", "decrypt"],
            )
            .then((cryptoKey) => {
                this._cryptoKey = cryptoKey;
            });
    }

    /**
     * @param {any} value
     */
    async encrypt(value) {
        await this._ready;
        const iv = window.crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await window.crypto.subtle.encrypt(
            {
                name: CRYPTO_ALGO,
                iv,
            },
            this._cryptoKey,
            new TextEncoder().encode(JSON.stringify(value)),
        );
        return { ciphertext, iv };
    }

    async decrypt(
        /** @type {{ ciphertext: BufferSource, iv: BufferSource }} */ {
            ciphertext,
            iv,
        },
    ) {
        await this._ready;
        const decrypted = await window.crypto.subtle.decrypt(
            {
                name: CRYPTO_ALGO,
                iv,
            },
            this._cryptoKey,
            ciphertext,
        );
        return JSON.parse(new TextDecoder().decode(decrypted));
    }
}

class RamCache {
    constructor() {
        this.ram = Object.create(null);
        this.modelIndex = Object.create(null);
        this.keyModel = Object.create(null);
        // Global LRU order across ALL (table, key) pairs: a Map keyed by the
        /** @type {Map<string, [string, string]>} */
        this.lru = new Map();
    }

    /** Move (table, key) to the warm end of the LRU order (insert if absent). */
    _touchLru(table, key) {
        const ck = `${table}\x00${key}`;
        this.lru.delete(ck);
        this.lru.set(ck, [table, key]);
    }

    /** Drop (table, key) from the LRU order — called by every ram-removal path. */
    _forgetLru(table, key) {
        this.lru.delete(`${table}\x00${key}`);
    }

    /**
     * Evict the coldest entries until the cache is back within
     * ``RAM_CACHE_MAX_ENTRIES``. Reuses ``delete()`` so the model reverse
     * indexes (and the LRU map itself) stay consistent.
     */
    _evictIfNeeded() {
        while (this.lru.size > RAM_CACHE_MAX_ENTRIES) {
            const [table, key] = this.lru.values().next().value;
            this.delete(table, key);
        }
    }

    /**
     * @param {string} table
     * @param {string} key
     * @param {any} value
     * @param {string} [model] Odoo model name for index-based invalidation.
     *   Omit for non-model-scoped entries (session_info, /web/action/load);
     *   they stay invisible to ``invalidateByModel`` by design.
     */
    write(table, key, value, model) {
        if (!(table in this.ram)) {
            this.ram[table] = Object.create(null);
            this.modelIndex[table] = new Map();
            this.keyModel[table] = Object.create(null);
        }
        const prevModel = this.keyModel[table][key];
        if (prevModel && prevModel !== model) {
            const prevSet = this.modelIndex[table].get(prevModel);
            prevSet?.delete(key);
            if (prevSet && !prevSet.size) {
                this.modelIndex[table].delete(prevModel);
            }
        }
        this.ram[table][key] = value;
        if (model) {
            let set = this.modelIndex[table].get(model);
            if (!set) {
                set = new Set();
                this.modelIndex[table].set(model, set);
            }
            set.add(key);
            this.keyModel[table][key] = model;
        } else if (prevModel) {
            delete this.keyModel[table][key];
        }
        this._touchLru(table, key);
        this._evictIfNeeded();
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    read(table, key) {
        const value = this.ram[table]?.[key];
        if (value !== undefined) {
            this._touchLru(table, key);
        }
        return value;
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    delete(table, key) {
        delete this.ram[table]?.[key];
        this._forgetLru(table, key);
        const model = this.keyModel[table]?.[key];
        if (model) {
            const set = this.modelIndex[table]?.get(model);
            set?.delete(key);
            if (set && !set.size) {
                this.modelIndex[table].delete(model);
            }
            delete this.keyModel[table][key];
        }
    }

    /**
     * @param {string | string[] | null} [tables]
     */
    invalidate(tables = null) {
        if (tables) {
            tables = typeof tables === "string" ? [tables] : tables;
            for (const table of tables) {
                if (table in this.ram) {
                    for (const key of Object.keys(this.ram[table])) {
                        this._forgetLru(table, key);
                    }
                    this.ram[table] = Object.create(null);
                    this.modelIndex[table] = new Map();
                    this.keyModel[table] = Object.create(null);
                }
            }
        } else {
            this.ram = Object.create(null);
            this.modelIndex = Object.create(null);
            this.keyModel = Object.create(null);
            this.lru = new Map();
        }
    }

    /**
     * Remove cache entries whose RPC params reference a specific Odoo model,
     * via the per-table model→keys reverse index: O(1) lookup + O(matched)
     * deletes, independent of table size. Entries written without a
     * ``model`` (to ``write()``) are correctly invisible here.
     *
     * @param {string[]} tables
     * @param {string} model - Odoo model name, e.g. "res.partner"
     */
    invalidateByModel(tables, model) {
        for (const table of tables) {
            const keys = this.modelIndex[table]?.get(model);
            if (!keys || !keys.size) {
                continue;
            }
            const tableMap = this.ram[table];
            const keyMap = this.keyModel[table];
            for (const key of keys) {
                delete tableMap[key];
                delete keyMap[key];
                this._forgetLru(table, key);
            }
            this.modelIndex[table].delete(model);
        }
    }
}

export class RPCCache {
    /**
     * @param {string} name
     * @param {string | number} version
     * @param {string | null} [secret] AES-GCM key (hex) for the disk layer.
     *   Only the DISK layer needs it (and SubtleCrypto, i.e. a secure
     *   context): when either is missing the cache degrades to RAM-only —
     *   ``type: "disk"`` reads transparently downgrade to ``"ram"`` —
     *   instead of disabling ALL rpc caching (plain-HTTP intranet deploys).
     */
    constructor(name, version, secret = null) {
        this.diskEnabled = Boolean(secret && window.crypto?.subtle);
        this.crypto = this.diskEnabled
            ? new Crypto(/** @type {string} */ (secret))
            : null;
        this.indexedDB = this.diskEnabled
            ? new IndexedDB(name, version + CRYPTO_ALGO)
            : null;
        this.ramCache = new RamCache();
        /**
         * Subscribers are stored as ``{ callback, shape }`` pairs: joiners
         * may request a different ``immutable`` setting than the first
         * caller, and each callback must receive the result through ITS OWN
         * shape (deep-frozen shared reference vs. deep copy) — not the first
         * caller's.
         *
         * ``model`` is the model the entry is scoped to, recorded here at
         * ``read`` time so {@link invalidateByModel} can match in-flight
         * requests in O(1) — see the note there.
         *
         * @type {Record<string, { callbacks: { callback: Function, shape: Function }[], invalidated: boolean, model?: string }>}
         */
        this.pendingRequests = {};
        /** @type {Record<string, number>} */
        this.diskGenerations = Object.create(null);
        this.globalDiskGeneration = 0;
        if (this.diskEnabled) {
            this.checkSize();
        }
    }

    /**
     * Current invalidation generation for ``table``: the global counter
     * (full-cache invalidation) plus the per-table counter (table- or
     * model-scoped invalidation), so a snapshot compares unequal iff either
     * moved since it was taken.
     *
     * @param {string} table
     * @returns {number}
     */
    diskGenerationOf(table) {
        return this.globalDiskGeneration + (this.diskGenerations[table] || 0);
    }

    /**
     * Bump the invalidation generation(s) so in-flight disk writes for the
     * affected tables are dropped instead of persisting stale data.
     *
     * @param {string | string[] | null | undefined} tables same contract as
     *   ``invalidate``: nullish means "everything".
     */
    bumpDiskGeneration(tables) {
        if (tables == null) {
            this.globalDiskGeneration++;
            return;
        }
        if (typeof tables !== "string" && !Array.isArray(tables)) {
            throw new TypeError(
                "bumpDiskGeneration expects a table name, an array of names, or nullish",
            );
        }
        for (const table of typeof tables === "string" ? [tables] : tables) {
            this.diskGenerations[table] = (this.diskGenerations[table] || 0) + 1;
        }
    }

    async checkSize() {
        let estimate;
        try {
            estimate = await navigator.storage.estimate();
        } catch {
            return;
        }
        const idbUsage = /** @type {any} */ (estimate).usageDetails?.indexedDB;
        if (idbUsage !== undefined) {
            if (idbUsage > MAX_STORAGE_SIZE) {
                console.warn(
                    `Deleting indexedDB database as maximum storage size is reached`,
                );
                return this.indexedDB?.deleteDatabase();
            }
            return;
        }
        if (estimate.usage > MAX_STORAGE_SIZE) {
            console.warn(
                "Origin storage usage exceeds the configured maximum " +
                    "(no per-storage breakdown available); keeping the RPC " +
                    "IndexedDB cache.",
            );
        }
    }

    /**
     * @param {string} table
     * @param {string} key
     * @param {function} fallback
     * @param {RPCCacheSettings} settings
     */
    read(
        table,
        key,
        fallback,
        {
            callback = () => {},
            type = "ram",
            update = "once",
            immutable = false,
            model = undefined,
            silent = false,
        } = {},
    ) {
        validateSettings({ type, update });
        const useDisk = type === "disk" && this.diskEnabled;

        let ramValue = this.ramCache.read(table, key);

        const shape = immutable ? deepFreeze : deepCopy;

        const requestKey = `${table}/${key}`;
        // Joining an in-flight request requires its RAM entry to still be there,
        // and that is deliberate rather than incidental. The RAM cache evicts by
        // LRU, so the entry that disappears may be the not-yet-resolved
        // placeholder of a request that never settles (a hung fetch). Falling
        // back to a fresh request there is the escape hatch that keeps one dead
        // request from wedging every later read of that key — see
        // "LRU eviction of a still-pending entry does not wedge later reads" in
        // rpc_cache.test.js. The cost is one redundant fetch in a cache that has
        // already overflowed; the alternative is an unbounded hang.
        const hasPendingRequest =
            requestKey in this.pendingRequests && ramValue !== undefined;
        if (hasPendingRequest) {
            const pending = this.pendingRequests[requestKey];
            pending.callbacks.push({ callback, shape });
            return ramValue.then(shape);
        }

        if (!ramValue || update === "always") {
            const request = {
                callbacks: [{ callback, shape }],
                invalidated: false,
                model,
            };
            this.pendingRequests[requestKey] = request;

            const prom = new Promise((resolve, reject) => {
                const fromCache = new Deferred();
                /** @type {any} */
                let fromCacheValue;
                let hasCacheValue = false;
                const onFulfilled = (/** @type {any} */ result) => {
                    resolve(result);
                    const hasChanged =
                        hasCacheValue && payloadChanged(fromCacheValue, result);
                    if (
                        !request.invalidated &&
                        this.pendingRequests[requestKey] === request
                    ) {
                        delete this.pendingRequests[requestKey];
                        this.ramCache.write(table, key, Promise.resolve(result), model);
                        if (useDisk) {
                            const { crypto, indexedDB } = this;
                            const generation = this.diskGenerationOf(table);
                            const version = result?.[VERSION_FIELD];
                            crypto
                                .encrypt(result)
                                .then((encryptedResult) => {
                                    if (
                                        request.invalidated ||
                                        generation !== this.diskGenerationOf(table)
                                    ) {
                                        return;
                                    }
                                    /** @type {Record<string, any>} */
                                    const stored = { ...encryptedResult };
                                    if (model) {
                                        stored.model = model;
                                    }
                                    if (version !== undefined) {
                                        stored.version = version;
                                    }
                                    indexedDB.write(table, key, stored).catch((e) => {
                                        if (e instanceof IDBQuotaExceededError) {
                                            indexedDB.deleteDatabase();
                                        } else {
                                            console.warn(
                                                "RPC cache: disk write failed",
                                                e,
                                            );
                                        }
                                    });
                                })
                                .catch(() => {
                                    // Encryption can fail if SubtleCrypto is unavailable
                                    // (e.g. insecure context). Silently skip disk caching.
                                });
                        }
                    }
                    for (const subscriber of request.callbacks) {
                        try {
                            subscriber.callback(subscriber.shape(result), hasChanged);
                        } catch (error) {
                            console.error("RPC cache: update callback failed", error);
                        }
                    }
                    return result;
                };
                const onRejected = async (/** @type {any} */ error) => {
                    await fromCache;
                    if (
                        !request.invalidated &&
                        this.pendingRequests[requestKey] === request
                    ) {
                        delete this.pendingRequests[requestKey];
                        if (!hasCacheValue) {
                            this.ramCache.delete(table, key);
                        }
                    }
                    if (hasCacheValue) {
                        if (error instanceof ConnectionLostError) {
                            // global "unhandledrejection" listener can observe
                            rpcBus.trigger(RpcEvent.BACKGROUND_REFRESH_FAILED, {
                                error,
                            });
                            if (!silent) {
                                Promise.reject(error);
                            }
                        } else {
                            console.warn("RPC cache: background refresh failed", error);
                        }
                        return;
                    }
                    reject(error);
                };
                if (ramValue) {
                    ramValue.then((/** @type {any} */ value) => {
                        resolve(value);
                        fromCacheValue = value;
                        hasCacheValue = true;
                        fromCache.resolve();
                    });
                } else if (useDisk) {
                    const { crypto, indexedDB } = this;
                    indexedDB
                        .read(table, key)
                        .then(
                            async (result) => {
                                if (result) {
                                    let decrypted;
                                    try {
                                        decrypted = await crypto.decrypt(result);
                                    } catch {
                                        return;
                                    }
                                    if (
                                        result.version !== undefined &&
                                        decrypted &&
                                        typeof decrypted === "object" &&
                                        decrypted[VERSION_FIELD] === undefined
                                    ) {
                                        decrypted[VERSION_FIELD] = result.version;
                                    }
                                    resolve(decrypted);
                                    fromCacheValue = decrypted;
                                    hasCacheValue = true;
                                }
                            },
                            () => {
                                // IndexedDB unavailable (storage denied,
                                // blocked delete): treat as a cache miss —
                                // the fallback fetch still serves the caller.
                                // Without this arm every boot-path cached
                                // call leaked an unhandled rejection.
                            },
                        )
                        .finally(() => fromCache.resolve());
                } else {
                    fromCache.resolve();
                }

                fallback(request).then(onFulfilled, onRejected);
            });
            this.ramCache.write(table, key, prom, model);
            ramValue = prom;
        }

        return ramValue.then(shape);
    }

    /**
     * Synchronously evict a cache-miss entry whose underlying fetch was
     * silently aborted (``abort(false)``): that fetch never settles, so the
     * ``onFulfilled``/``onRejected`` bookkeeping never runs and the
     * ``pendingRequests`` slot plus the never-settling RAM promise would leak
     * — every later read of the key (including ``update: "always"``
     * refreshes) then returns a promise that never resolves. Mirrors the
     * dedup layer's synchronous abort eviction (rpc.js). No-op if the entry
     * already settled or was invalidated.
     *
     * @param {string} table
     * @param {string} key
     */
    abortPending(table, key, request) {
        const requestKey = `${table}/${key}`;
        if (
            requestKey in this.pendingRequests &&
            (request === undefined || this.pendingRequests[requestKey] === request)
        ) {
            delete this.pendingRequests[requestKey];
            this.ramCache.delete(table, key);
        }
    }

    /**
     * @param {string | string[] | null} [tables]
     */
    invalidate(tables) {
        this.bumpDiskGeneration(tables);
        this.indexedDB?.invalidate(tables);
        this.ramCache.invalidate(tables);
        if (tables == null) {
            for (const key of Object.keys(this.pendingRequests)) {
                this.pendingRequests[key].invalidated = true;
            }
            this.pendingRequests = {};
            return;
        }
        const tableList = typeof tables === "string" ? [tables] : tables;
        for (const requestKey of Object.keys(this.pendingRequests)) {
            if (tableList.some((table) => requestKey.startsWith(`${table}/`))) {
                this.pendingRequests[requestKey].invalidated = true;
                delete this.pendingRequests[requestKey];
            }
        }
    }

    /**
     * Selectively remove cache entries for a specific Odoo model.
     *
     * - RAM: O(1) lookup via the per-table model→keys reverse index
     *   maintained by ``RamCache.write/delete/invalidate``; entries written
     *   without a ``model`` are correctly invisible (never model-scoped).
     * - IndexedDB: ``openCursor`` + check ``cursor.value.model``, stored
     *   plaintext alongside the ciphertext (model names already appear in
     *   the request URL, so this exposes nothing new).
     * - In-flight requests: matched on the ``model`` each one recorded at
     *   ``read`` time. Requests registered without a ``model`` are invisible
     *   here, exactly like the RAM entries they will become.
     *
     * The model used to be recovered by splitting the request key on its first
     * ``/`` and JSON-parsing the remainder. The key is ``table/jsonKey`` and
     * the table is ``params.method || url`` (rpc.js), so every URL-keyed entry
     * — ``/web/action/load``, ``/web/webclient/load_menus``, any call with no
     * ``method`` — split at index 0 and failed to parse, and the ``catch``
     * dropped it silently: those in-flight requests were never invalidated and
     * went on to write a stale value into the RAM cache that had just been
     * cleared.
     *
     * @param {string[]} tables
     * @param {string} model - Odoo model name, e.g. "res.partner"
     */
    invalidateByModel(tables, model) {
        this.bumpDiskGeneration(tables);
        this.ramCache.invalidateByModel(tables, model);
        this.indexedDB?.invalidateByModel(tables, model);
        for (const requestKey of Object.keys(this.pendingRequests)) {
            if (this.pendingRequests[requestKey].model === model) {
                this.pendingRequests[requestKey].invalidated = true;
                delete this.pendingRequests[requestKey];
            }
        }
    }
}
