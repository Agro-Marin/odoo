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
 * ``model`` is the Odoo model name (e.g. ``"res.partner"``) the request
 * targets. When supplied, the entry joins a per-table model→keys reverse
 * index so ``invalidateByModel`` runs in O(1) instead of scanning + parsing
 * every key. Callers pass ``params.model`` from the JSON-RPC payload.
 */

/**
 * Server-emitted content-hash field that the cache uses to skip the deep
 * compare on stale-while-revalidate refreshes (``update: "always"`` consumers).
 * Endpoints that opt in inject this field into their dict return value; the
 * cache compares versions in O(1) instead of deep-serializing both payloads.
 *
 * See ``addons/core/addons/web/models/web_search_panel.py`` for the canonical
 * server-side stamping pattern (sha256 of canonical JSON).
 */
const VERSION_FIELD = "__version";

/**
 * O(1) structural disqualifier: ``true`` when the two payloads cannot
 * possibly be equal because their top-level shape differs (array vs
 * object, different lengths, different key counts).  ``false`` means
 * "shape matches — caller must run the full compare to know".
 *
 * Catches the common "row appended / row removed" case in
 * list-returning cached endpoints (``web_read``, template dropdowns,
 * m2o special data) without serializing.  Benchmark: ~400× faster than
 * a full deep compare on a 200-record list when length differs by one.
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
 *
 *   1. Reference equality (``===``).
 *   2. Version-hash compare when both sides carry ``__version`` (Plan C —
 *      endpoints opted in via the ``versioned`` decorator).
 *   3. Structural shape disqualifier (``Array.length`` / ``Object.keys.length``).
 *   4. Full order-independent deep compare via ``deepEqual``. (A previous
 *      ``JSON.stringify`` byte-compare was key-order-fragile: the server can
 *      emit dict keys in a different insertion order across two runs of the
 *      same query — the reason ``__version`` hashing uses ``sort_keys=True`` —
 *      which made it report a spurious change and needlessly re-deliver +
 *      re-persist identical payloads on every refresh.)
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
 * Recursively freeze a value in place.  Idempotent: on an already-frozen
 * root the function short-circuits at O(1) thanks to the
 * ``Object.isFrozen`` guard (we always freeze leaves before the root, so a
 * frozen root implies a fully-frozen subtree).  Returns the same reference
 * for convenience in expressions.
 *
 * @template T
 * @param {T} value
 * @returns {T}
 */
function deepFreeze(value) {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
        // TS narrows ``value`` to ``object`` after the typeof check but
        // ``object`` is not string-indexable. Cast to a string-indexed
        // record so the recursion typechecks; runtime behaviour is
        // unchanged because ``Object.keys`` already returned the
        // string keys we walk here.
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
        // Per-table reverse index: model → Set<key>.  Maintained by
        // ``write``/``delete``/``invalidate`` so ``invalidateByModel`` is
        // O(1) lookup + O(matched) delete instead of O(table size) with
        // a ``JSON.parse(key)`` per entry.  Benchmark on a 1000-entry
        // table: ~2,000× faster.  Mirrors ``this.ram`` lifecycle exactly
        // (same tables exist on both sides).
        this.modelIndex = Object.create(null);
        // Per-table flat map of key → model so ``delete(table, key)`` can
        // find which Set to remove the key from without the caller
        // re-supplying the model.  Stored separately from the value (vs
        // a wrapper object on ``ram[table][key]``) because ``read`` is on
        // the hot path and must not pay a property-access tax.
        this.keyModel = Object.create(null);
    }

    /**
     * @param {string} table
     * @param {string} key
     * @param {any} value
     * @param {string} [model] Odoo model name for index-based invalidation.
     *   Omit for entries that are not model-scoped (session_info,
     *   /web/action/load, etc.) — they will be invisible to
     *   ``invalidateByModel`` (correct: those use ``invalidate(table)``).
     */
    write(table, key, value, model) {
        if (!(table in this.ram)) {
            this.ram[table] = Object.create(null);
            this.modelIndex[table] = new Map();
            this.keyModel[table] = Object.create(null);
        }
        // Track previous model so an overwrite of the same key with a
        // different model (rare but possible — same URL, different
        // params.model) cleans up the old index entry.  Prune the old
        // model→Set when it becomes empty so ``modelIndex[t].has(m)``
        // reports ``false`` instead of a stale empty Set sticking around.
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
     * Remove only cache entries whose RPC params reference a specific Odoo model.
     * Uses the per-table model→keys reverse index, so cost is O(1) for the
     * lookup plus O(matched) for the actual deletes — independent of how
     * many other models' entries live in the same table.
     *
     * Entries written without a ``model`` argument to ``write()`` are
     * invisible to this method (correct — they are not model-scoped).
     * The old JSON.parse-each-key behaviour is gone; malformed keys
     * never enter the index in the first place.
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
        // Monotonic invalidation generations guarding the async disk-write
        // chain (see ``read``).  ``invalidate``/``invalidateByModel`` can no
        // longer flag a request once ``onFulfilled`` removed it from
        // ``pendingRequests``, yet the encrypt→IDB-write chain is still in
        // flight at that point: the IDB clear is queued on the mutex FIRST
        // and the write would land AFTER it, durably persisting
        // pre-invalidation data (served as truth on the next reload for
        // ``update: "once"`` consumers such as get_views).  The write chain
        // snapshots the table's generation when the result arrives and skips
        // the persist when an invalidation bumped it in between.  Per-table
        // (plus a global counter for the full-cache nuke, where the affected
        // table set is unknown) so an invalidation of one table never
        // discards a concurrent, still-valid write of an unrelated table.
        /** @type {Record<string, number>} */
        this.diskGenerations = Object.create(null);
        this.globalDiskGeneration = 0;
        this.checkSize(); // we want to control the disk space used by Odoo
    }

    /**
     * Current invalidation generation for ``table``.  Monotonically
     * increasing: the sum of the global counter (bumped by full-cache
     * invalidation) and the per-table counter (bumped by table- or
     * model-scoped invalidation), so a snapshot compares unequal iff either
     * counter moved since it was taken.
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

        // Pick the value-shaping pass once.  Immutable callers receive the
        // shared cached reference (deep-frozen on first delivery; subsequent
        // ``deepFreeze`` calls O(1) thanks to the ``Object.isFrozen`` guard)
        // so any caller mutation throws synchronously.  The default
        // ``deepCopy`` clones via ``structuredClone``, which is 100×+ slower
        // per call for typical record payloads.
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

            // execute the fallback and write the result in the caches
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
                    // throwing callback can never leave the key wedged (a dead
                    // entry in ``pendingRequests`` that every future read
                    // would join, killing all `update: "always"` refreshes).
                    if (!request.invalidated) {
                        // (When invalidated mid-flight, `invalidate`/
                        // `invalidateByModel` already removed the entry and
                        // the caches: don't persist stale data.)
                        delete this.pendingRequests[requestKey];
                        // update the ram and optionally the disk caches with the latest data
                        this.ramCache.write(table, key, Promise.resolve(result), model);
                        if (type === "disk") {
                            // Snapshot the invalidation generation NOW: the
                            // request is no longer in ``pendingRequests``, so
                            // an invalidation arriving during the async
                            // encrypt below can't flag it — the generation
                            // compare is what keeps its stale payload out of
                            // IndexedDB (the clear is queued on the mutex
                            // first; an unguarded write would land after it).
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
                                    // Store model plaintext alongside the
                                    // ciphertext so ``invalidateByModel`` can
                                    // filter on it without decrypting every
                                    // entry.  Model names are not secret
                                    // (they appear in the URL) so plaintext
                                    // here is fine.
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
                    // Always notify pending callbacks — subscribers explicitly
                    // requested server data via `update: "always"`. The RPC result
                    // is fresh regardless of whether the cache was invalidated.
                    // Each callback is guarded: one throwing subscriber must not
                    // starve the others nor escape as an unhandled rejection.
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
                            this.ramCache.delete(table, key); // remove rejected prom from ram cache
                        }
                    }
                    if (hasCacheValue) {
                        // Promise was already fulfilled with cached value — the
                        // caller already got its data, so don't reject.  But if
                        // the failure is a ConnectionLostError we must still
                        // surface it so the global error service (which listens on
                        // "unhandledrejection") can show the connection-lost
                        // notification to the user.
                        if (error instanceof ConnectionLostError) {
                            Promise.reject(error);
                        } else {
                            console.warn("RPC cache: background refresh failed", error);
                        }
                        return;
                    }
                    reject(error);
                };
                // Speed up the request by using the caches.  Attach the
                // cache-read .then BEFORE the fallback handler so the
                // microtask draining `fromCacheValue = value` runs before
                // `onFulfilled`.  Otherwise — when both promises are
                // pre-resolved (typical mocked-RPC test, but also any
                // sufficiently fast cache hit) — `onFulfilled` would
                // observe `hasCacheValue === false` and short-circuit
                // `hasChanged` to false, silently masking real refreshes.
                if (ramValue) {
                    // ramValue is always already resolved here, as it can't be pending (otherwise
                    // we would have early returned because of `pendingRequests`) and it would have
                    // been removed from the ram cache if it had been rejected
                    // => no need to define a `catch` callback.
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
     * - RAM cache: O(1) lookup via per-table model→keys reverse index
     *   maintained by ``RamCache.write/delete/invalidate``. No JSON.parse
     *   per entry; entries written without a ``model`` argument are
     *   correctly invisible (they were never model-scoped).
     * - IndexedDB: ``invalidateByModel`` uses ``openCursor`` and checks
     *   ``cursor.value.model`` — the property is stored plaintext
     *   alongside the encrypted ciphertext (model names appear in the
     *   request URL, so plaintext exposes nothing new).
     * - In-flight requests: the few currently pending RPCs are scanned;
     *   parse cost here is negligible (typically 0–3 entries).
     *
     * Pre-2026-05 the RAM side parsed every key and the IDB side wiped
     * the whole table; both replaced here.
     *
     * @param {string[]} tables
     * @param {string} model - Odoo model name, e.g. "res.partner"
     */
    invalidateByModel(tables, model) {
        // Conservative: bumps the whole table's generation even though the
        // signal is model-scoped, so a concurrent disk write for another
        // model in the same table may be skipped too.  The cost is a cache
        // miss on next reload — never stale data — and it avoids threading
        // the model through the generation bookkeeping.
        this.bumpDiskGeneration(tables);
        this.ramCache.invalidateByModel(tables, model);
        this.indexedDB.invalidateByModel(tables, model);
        // Cancel in-flight requests whose key includes this model.
        // requestKey format is "${table}/${JSON.stringify({url, params})}" —
        // slice past the first "/" to recover the JSON portion. The set
        // is tiny in practice (concurrent RPCs against the same model
        // are rare), so per-key parsing here is acceptable.
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
