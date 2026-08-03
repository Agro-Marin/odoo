// @ts-check
/** @odoo-module native */

/** @module @web/core/network/rpc_cache */

import { browser } from "@web/core/browser/browser";
import { reportUncaught } from "@web/core/errors/error_utils";
import { RpcEvent } from "@web/core/events";
import {
    ConnectionAbortedError,
    ConnectionLostError,
    rpcBus,
} from "@web/core/network/rpc";
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
 */

const VERSION_FIELD = "__version";

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
 * @param {any} fromCacheValue
 * @param {any} result
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
 * ``Object.freeze`` happens after the recursion, so a value that reaches itself
 * is not yet frozen when it comes back round: the ``isFrozen`` check cannot end
 * the walk, and a cycle overflowed the stack. RPC payloads are JSON today, but
 * this also runs over whatever a caller hands ``read()`` in a test.
 *
 * @template T
 * @param {T} value
 * @param {WeakSet<object>} [seen]
 * @returns {T}
 */
function deepFreeze(value, seen = new WeakSet()) {
    if (value && typeof value === "object" && !Object.isFrozen(value)) {
        if (seen.has(value)) {
            return value;
        }
        seen.add(value);
        const indexable = /** @type {Record<string, unknown>} */ (value);
        for (const key of Object.keys(indexable)) {
            deepFreeze(indexable[key], seen);
        }
        Object.freeze(value);
    }
    return value;
}

const CRYPTO_ALGO = "AES-GCM";
const MAX_STORAGE_SIZE = 2 * 1024 * 1024 * 1024;

export const RAM_CACHE_MAX_ENTRIES = 10000;

class Crypto {
    /**
     * @param {string} secret
     */
    constructor(secret) {
        const bytes = secret.match(/../g) ?? [];
        /**
         * @type {Promise<CryptoKey>}
         */
        this._key = browser.crypto.subtle.importKey(
            "raw",
            new Uint8Array(bytes.map((h) => Number.parseInt(h, 16))).buffer,
            CRYPTO_ALGO,
            false,
            ["encrypt", "decrypt"],
        );
    }

    /**
     * @param {any} value
     */
    async encrypt(value) {
        const key = await this._key;
        const iv = browser.crypto.getRandomValues(new Uint8Array(12));
        const ciphertext = await browser.crypto.subtle.encrypt(
            {
                name: CRYPTO_ALGO,
                iv,
            },
            key,
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
        const key = await this._key;
        const decrypted = await browser.crypto.subtle.decrypt(
            {
                name: CRYPTO_ALGO,
                iv,
            },
            key,
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
        /** @type {Map<string, [string, string]>} */
        this.lru = new Map();
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    _touchLru(table, key) {
        const ck = `${table}\x00${key}`;
        this.lru.delete(ck);
        this.lru.set(ck, [table, key]);
    }

    /**
     * @param {string} table
     * @param {string} key
     */
    _forgetLru(table, key) {
        this.lru.delete(`${table}\x00${key}`);
    }

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
     * @param {string} [model]
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
     * @param {string[]} tables
     * @param {string} model
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
     * @param {string | null} [secret]
     */
    constructor(name, version, secret = null) {
        this.diskEnabled = Boolean(secret && browser.crypto?.subtle);
        this.crypto = this.diskEnabled
            ? new Crypto(/** @type {string} */ (secret))
            : null;
        this.indexedDB = this.diskEnabled
            ? new IndexedDB(name, version + CRYPTO_ALGO)
            : null;
        this.ramCache = new RamCache();
        /**
         * @type {Record<string, { callbacks: { callback: Function, shape: Function }[], invalidated: boolean, model?: string }>}
         */
        this.pendingRequests = Object.create(null);
        /** @type {Record<string, number>} */
        this.diskGenerations = Object.create(null);
        this.globalDiskGeneration = 0;
        if (this.diskEnabled) {
            this.checkSize();
        }
    }

    /**
     * @param {string} table
     * @returns {number}
     */
    diskGenerationOf(table) {
        return this.globalDiskGeneration + (this.diskGenerations[table] || 0);
    }

    /**
     * @param {string | string[] | null | undefined} tables
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
            estimate = await browser.navigator.storage.estimate();
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
        if ((estimate.usage ?? 0) > MAX_STORAGE_SIZE) {
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
            // No default no-op: `shape` is a full `deepCopy` of the payload,
            // and it was being run to feed a callback that discards it. Half of
            // every cached read's cloning was thrown away.
            callback,
            type = "ram",
            update = "once",
            immutable = false,
            model = undefined,
            silent = false,
        } = {},
    ) {
        validateSettings({ type, update });
        /** @type {{ crypto: Crypto, indexedDB: IndexedDB } | null} */
        const useDisk =
            type === "disk" && this.crypto && this.indexedDB
                ? { crypto: this.crypto, indexedDB: this.indexedDB }
                : null;

        let ramValue = this.ramCache.read(table, key);

        const shape = immutable ? deepFreeze : deepCopy;

        const requestKey = `${table}/${key}`;
        const hasPendingRequest =
            Object.hasOwn(this.pendingRequests, requestKey) && ramValue !== undefined;
        if (hasPendingRequest) {
            const pending = this.pendingRequests[requestKey];
            if (callback) {
                pending.callbacks.push({ callback, shape });
            }
            return ramValue.then(shape);
        }

        if (!ramValue || update === "always") {
            const request = {
                callbacks: callback ? [{ callback, shape }] : [],
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
                    // `payloadChanged` deep-compares the whole payload and its
                    // only consumer is the subscriber loop below, so it is not
                    // worth computing when nobody subscribed.
                    const hasChanged =
                        hasCacheValue &&
                        request.callbacks.length > 0 &&
                        payloadChanged(fromCacheValue, result);
                    if (
                        !request.invalidated &&
                        this.pendingRequests[requestKey] === request
                    ) {
                        delete this.pendingRequests[requestKey];
                        this.ramCache.write(table, key, Promise.resolve(result), model);
                        if (useDisk) {
                            const { crypto, indexedDB } = useDisk;
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
                                .catch(() => {});
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
                        if (error instanceof ConnectionAbortedError) {
                            // The caller dropped its own refresh -- `rpc`'s
                            // `abort()` rejects the inner request with this.
                            // That is not a failure to report: it is the one
                            // outcome the caller asked for, and warning about it
                            // put a console line under every aborted
                            // `update: "always"` read.
                            return;
                        }
                        if (error instanceof ConnectionLostError) {
                            // Genuine connectivity loss -> the app is offline.
                            // InvalidResponseError is no longer a ConnectionLostError
                            // (e.g. a session-expired refresh returned a login page),
                            // so it falls to the plain warning below rather than
                            // signalling offline; session expiry surfaces on the next
                            // real user action.
                            rpcBus.trigger(RpcEvent.BACKGROUND_REFRESH_FAILED, {
                                error,
                            });
                            if (!silent) {
                                reportUncaught(error);
                            }
                        } else {
                            console.warn("RPC cache: background refresh failed", error);
                        }
                        return;
                    }
                    reject(error);
                };
                if (ramValue) {
                    // `onRejected` waits on `fromCache` before doing anything,
                    // so the gate has to open on both settlements -- the disk
                    // branch below already opens it from a `finally`. Opening
                    // it only on fulfilment meant a cached promise that
                    // rejected left this read's own failure stuck behind a gate
                    // nobody would open again.
                    ramValue.then(
                        (/** @type {any} */ value) => {
                            resolve(value);
                            fromCacheValue = value;
                            hasCacheValue = true;
                            fromCache.resolve();
                        },
                        () => {
                            this.ramCache.delete(table, key);
                            fromCache.resolve();
                        },
                    );
                } else if (useDisk) {
                    const { crypto, indexedDB } = useDisk;
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
                            () => {},
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
     * @param {string} table
     * @param {string} key
     * @param {object} [request] the entry this caller owns, so a caller that
     *  aborts after its own request was superseded drops nothing
     */
    abortPending(table, key, request) {
        const requestKey = `${table}/${key}`;
        if (
            Object.hasOwn(this.pendingRequests, requestKey) &&
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
            this.pendingRequests = Object.create(null);
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
     * @param {string[]} tables
     * @param {string} model
     */
    invalidateByModel(tables, model) {
        this.bumpDiskGeneration(tables);
        this.ramCache.invalidateByModel(tables, model);
        this.indexedDB?.invalidateByModel(tables, model);
        // Scoped by table, like ram and disk two lines up and like
        // `invalidate()`. Matching on the model alone dropped a request whose
        // table nobody asked about while leaving its ram entry in place, and an
        // invalidated request skips the cleanup in `onRejected` -- which is how
        // a rejected promise ended up cached under a live key.
        for (const requestKey of Object.keys(this.pendingRequests)) {
            const request = this.pendingRequests[requestKey];
            if (
                request.model === model &&
                tables.some((table) => requestKey.startsWith(`${table}/`))
            ) {
                request.invalidated = true;
                delete this.pendingRequests[requestKey];
            }
        }
    }

    /**
     * Delete the persisted (on-disk) cache entirely. Unlike `invalidate`, which
     * marks entries stale but keeps the IndexedDB database, this removes the
     * database itself -- used on logout so one user's cached model/table
     * metadata does not outlive their session on a shared browser (the disk
     * store survives a normal navigation; the RAM cache does not). Resolves even
     * when the delete is blocked or unavailable, so logout never hangs on it.
     *
     * @returns {Promise<void>}
     */
    async purgeStorage() {
        await this.indexedDB?.deleteDatabase();
    }
}
