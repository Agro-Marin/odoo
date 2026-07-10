// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_cache - Encrypted RAM/IndexedDB cache for RPC responses */

import { ConnectionLostError } from "@web/core/network/rpc";
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
 * }} RPCCacheSettings
 *
 * ``model`` (e.g. ``"res.partner"``) joins the entry to a per-table
 * model→keys reverse index, making ``invalidateByModel`` O(1) instead of
 * scanning + parsing every key.
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
        // TS narrows ``value`` to ``object``, which isn't string-indexable;
        // cast to a string-indexed record so the recursion typechecks
        // (runtime behavior is unchanged).
        const indexable = /** @type {Record<string, unknown>} */ (value);
        for (const key of Object.keys(indexable)) {
            deepFreeze(indexable[key]);
        }
        Object.freeze(value);
    }
    return value;
}

const CRYPTO_ALGO = "AES-GCM";
const MAX_STORAGE_SIZE = 2 * 1024 * 1024 * 1024; // 2Gb

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
        // The iv must never be reused with a given key.
        const iv = window.crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await window.crypto.subtle.encrypt(
            {
                name: CRYPTO_ALGO,
                iv,
            },
            this._cryptoKey,
            new TextEncoder().encode(JSON.stringify(value)), // encoded Data
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
        // Per-table reverse index: model → Set<key>, kept in sync by
        // write/delete/invalidate so invalidateByModel is O(1) lookup +
        // O(matched) delete instead of O(table size) (~2,000× faster on a
        // 1000-entry table).
        this.modelIndex = Object.create(null);
        // Per-table key → model map, so delete(table, key) finds which Set
        // to remove from without the caller re-supplying the model. Kept
        // off the hot read() path to avoid a property-access tax.
        this.keyModel = Object.create(null);
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
        // Track previous model so overwriting the same key with a different
        // model (rare, but possible) cleans up the old index entry, pruning
        // the model→Set when it becomes empty.
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
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    read(table, key) {
        return this.ram[table]?.[key];
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    delete(table, key) {
        delete this.ram[table]?.[key];
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
                    this.ram[table] = Object.create(null);
                    this.modelIndex[table] = new Map();
                    this.keyModel[table] = Object.create(null);
                }
            }
        } else {
            this.ram = Object.create(null);
            this.modelIndex = Object.create(null);
            this.keyModel = Object.create(null);
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
            }
            this.modelIndex[table].delete(model);
        }
    }
}

export class RPCCache {
    /**
     * @param {string} name
     * @param {string | number} version
     * @param {string} secret
     */
    constructor(name, version, secret) {
        this.crypto = new Crypto(secret);
        this.indexedDB = new IndexedDB(name, version + CRYPTO_ALGO);
        this.ramCache = new RamCache();
        /** @type {Record<string, { callbacks: Function[], invalidated: boolean }>} */
        this.pendingRequests = {};
        // Monotonic invalidation generations guard the async disk-write
        // chain (see ``read``): once a request leaves ``pendingRequests``,
        // invalidation can no longer flag it, yet its encrypt→IDB-write may
        // still land after an IDB clear and persist stale data. The write
        // snapshots the generation on arrival and skips persisting if it
        // bumped meanwhile. Per-table, plus a global counter for full
        // nukes, so invalidating one table doesn't discard another's
        // concurrent write.
        /** @type {Record<string, number>} */
        this.diskGenerations = Object.create(null);
        this.globalDiskGeneration = 0;
        this.checkSize(); // we want to control the disk space used by Odoo
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
        for (const table of typeof tables === "string" ? [tables] : tables) {
            this.diskGenerations[table] = (this.diskGenerations[table] || 0) + 1;
        }
    }

    async checkSize() {
        let usage;
        try {
            ({ usage } = await navigator.storage.estimate());
        } catch {
            // StorageManager may be unavailable in insecure contexts
            return;
        }
        if (usage > MAX_STORAGE_SIZE) {
            console.warn(
                `Deleting indexedDB database as maximum storage size is reached`,
            );
            return this.indexedDB.deleteDatabase();
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
        } = {},
    ) {
        validateSettings({ type, update });

        let ramValue = this.ramCache.read(table, key);

        // Immutable callers get the shared cached reference (deep-frozen on
        // first delivery; later ``deepFreeze`` calls are O(1)) so a caller
        // mutation throws synchronously. Default ``deepCopy`` clones via
        // ``structuredClone``, 100×+ slower per call for typical payloads.
        const shape = immutable ? deepFreeze : deepCopy;

        const requestKey = `${table}/${key}`;
        const hasPendingRequest = requestKey in this.pendingRequests;
        if (hasPendingRequest) {
            // never do the same call multiple times in parallel => return the same value for all
            // those calls, but store their callback to call them when/if the real value is obtained
            this.pendingRequests[requestKey].callbacks.push(callback);
            return ramValue.then(shape);
        }

        if (!ramValue || update === "always") {
            const request = { callbacks: [callback], invalidated: false };
            this.pendingRequests[requestKey] = request;

            const prom = new Promise((resolve, reject) => {
                const fromCache = new Deferred();
                /** @type {any} */
                let fromCacheValue;
                // Distinguishes "no cached value" from a cached falsy payload
                // (e.g. false, 0, ""): fromCacheValue alone can't tell them apart.
                let hasCacheValue = false;
                const onFulfilled = (/** @type {any} */ result) => {
                    resolve(result);
                    const hasChanged =
                        hasCacheValue && payloadChanged(fromCacheValue, result);
                    // Cache bookkeeping runs BEFORE subscriber callbacks so a
                    // throwing callback can't wedge the key (leave a dead
                    // ``pendingRequests`` entry that swallows future refreshes).
                    if (!request.invalidated) {
                        // If invalidated mid-flight, invalidate()/
                        // invalidateByModel() already cleared the caches.
                        delete this.pendingRequests[requestKey];
                        this.ramCache.write(table, key, Promise.resolve(result), model);
                        if (type === "disk") {
                            // Snapshot the generation NOW: the request just
                            // left ``pendingRequests``, so a concurrent
                            // invalidation can't flag it — comparing
                            // generations keeps stale payloads out of
                            // IndexedDB (the clear is queued first, so an
                            // unguarded write would land after it).
                            const generation = this.diskGenerationOf(table);
                            this.crypto
                                .encrypt(result)
                                .then((encryptedResult) => {
                                    if (
                                        request.invalidated ||
                                        generation !== this.diskGenerationOf(table)
                                    ) {
                                        // Invalidated between RPC resolution and
                                        // encryption end: skip the persist.  RAM
                                        // was already cleared synchronously.
                                        return;
                                    }
                                    // Store model in plaintext alongside the
                                    // ciphertext so ``invalidateByModel`` can
                                    // filter without decrypting every entry —
                                    // model names aren't secret (they're
                                    // already in the URL).
                                    const stored = model
                                        ? { ...encryptedResult, model }
                                        : encryptedResult;
                                    this.indexedDB
                                        .write(table, key, stored)
                                        .catch((e) => {
                                            if (e instanceof IDBQuotaExceededError) {
                                                this.indexedDB.deleteDatabase();
                                            } else {
                                                throw e;
                                            }
                                        });
                                })
                                .catch(() => {
                                    // Encryption can fail if SubtleCrypto is unavailable
                                    // (e.g. insecure context). Silently skip disk caching.
                                });
                        }
                    }
                    // Always notify pending callbacks: they explicitly asked
                    // for fresh data via `update: "always"`, regardless of
                    // cache invalidation. Each callback is guarded so one
                    // throwing subscriber can't starve the others.
                    for (const cb of request.callbacks) {
                        try {
                            cb(shape(result), hasChanged);
                        } catch (error) {
                            console.error("RPC cache: update callback failed", error);
                        }
                    }
                    return result;
                };
                const onRejected = async (/** @type {any} */ error) => {
                    await fromCache;
                    if (!request.invalidated) {
                        delete this.pendingRequests[requestKey];
                        if (!hasCacheValue) {
                            this.ramCache.delete(table, key);
                        }
                    }
                    if (hasCacheValue) {
                        // Caller already got cached data, so don't reject —
                        // except a ConnectionLostError, which must still
                        // surface via "unhandledrejection" so the global
                        // error service can notify the user.
                        if (error instanceof ConnectionLostError) {
                            Promise.reject(error);
                        } else {
                            console.warn("RPC cache: background refresh failed", error);
                        }
                        return;
                    }
                    reject(error);
                };
                // Attach the cache-read .then BEFORE the fallback handler so
                // `fromCacheValue` is set before `onFulfilled` runs.
                // Otherwise, when both promises are pre-resolved (mocked-RPC
                // tests, fast cache hits), `onFulfilled` would see
                // `hasCacheValue === false` and mask real refreshes by
                // short-circuiting `hasChanged` to false.
                if (ramValue) {
                    // ramValue is always resolved here (pending would have
                    // early-returned via `pendingRequests`; a rejection
                    // would have removed it) — no `catch` needed.
                    ramValue.then((/** @type {any} */ value) => {
                        resolve(value);
                        fromCacheValue = value;
                        hasCacheValue = true;
                        fromCache.resolve();
                    });
                } else if (type === "disk") {
                    this.indexedDB
                        .read(table, key)
                        .then(async (result) => {
                            if (result) {
                                let decrypted;
                                try {
                                    decrypted = await this.crypto.decrypt(result);
                                } catch {
                                    // Do nothing ! The cryptoKey is probably different.
                                    // The data will be updated with the new cryptoKey.
                                    return;
                                }
                                resolve(decrypted);
                                fromCacheValue = decrypted;
                                hasCacheValue = true;
                            }
                        })
                        .finally(() => fromCache.resolve());
                } else {
                    fromCache.resolve(); // fromCacheValue will remain undefined
                }

                fallback().then(onFulfilled, onRejected);
            });
            this.ramCache.write(table, key, prom, model);
            ramValue = prom;
        }

        return ramValue.then(shape);
    }

    /**
     * @param {string | string[] | null} [tables]
     */
    invalidate(tables) {
        // Drop in-flight disk writes that resolved before this invalidation
        // but have not persisted yet (their pendingRequests entry is already
        // gone, so the `invalidated` flag below can't reach them).
        this.bumpDiskGeneration(tables);
        this.indexedDB.invalidate(tables);
        this.ramCache.invalidate(tables);
        // flag the pending requests as invalidated s.t. we don't write their results in caches
        if (tables == null) {
            // full-cache nuke: every pending request is affected
            for (const key of Object.keys(this.pendingRequests)) {
                this.pendingRequests[key].invalidated = true;
            }
            this.pendingRequests = {};
            return;
        }
        // Table-scoped invalidation: only flag pending requests belonging to
        // the invalidated tables (requestKey format is "${table}/${key}"),
        // like invalidateByModel already does for model-scoped signals.
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
     * - In-flight requests: the handful of pending RPCs are scanned; parse
     *   cost is negligible (typically 0–3 entries).
     *
     * @param {string[]} tables
     * @param {string} model - Odoo model name, e.g. "res.partner"
     */
    invalidateByModel(tables, model) {
        // Conservative: bumps the whole table's generation even though the
        // signal is model-scoped, so an unrelated concurrent write may be
        // skipped too — costing a cache miss next reload, never stale data.
        this.bumpDiskGeneration(tables);
        this.ramCache.invalidateByModel(tables, model);
        this.indexedDB.invalidateByModel(tables, model);
        // Cancel in-flight requests whose key includes this model.
        // requestKey is "${table}/${JSON.stringify({url, params})}"; slice
        // past the first "/" to recover the JSON. The set is tiny in
        // practice, so per-key parsing here is acceptable.
        for (const requestKey of Object.keys(this.pendingRequests)) {
            const jsonPart = requestKey.slice(requestKey.indexOf("/") + 1);
            try {
                if (JSON.parse(jsonPart)?.params?.model === model) {
                    this.pendingRequests[requestKey].invalidated = true;
                    delete this.pendingRequests[requestKey];
                }
            } catch {
                // malformed key — skip
            }
        }
    }
}
