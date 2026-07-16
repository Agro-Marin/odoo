// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/indexed_db - IndexedDB wrapper with versioned schema, quota management, and mutex locking */

import { browser } from "../browser/browser.js";
import { Mutex } from "./concurrency.js";

const VERSION_TABLE = "__DBVersion__";
const VERSION_KEY = "__version__";
/**
 * How long a blocked `deleteDatabase` — or a blocked version-bump `open`
 * (schema upgrade adding a missing object store, see ``_execute``) — may
 * wait for the other connections to close before this instance gives up and
 * degrades to no-cache for the session. Both run inside the instance mutex,
 * so waiting forever (e.g. on a frozen/bfcached tab that never receives
 * `versionchange`) would queue every subsequent read/write behind it —
 * worst case hanging the webclient boot after a deploy that bumps the
 * registry hash.
 */
const BLOCKED_DELETE_TIMEOUT = 1000;

export class IDBQuotaExceededError extends Error {}

function formatStorageSize(/** @type {number} */ size) {
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (size >= 1000 && i < units.length - 1) {
        size /= 1000;
        i++;
    }
    return `${size.toFixed(2)}${units[i]}`;
}

export class IndexedDB {
    constructor(/** @type {string} */ name, /** @type {string} */ version) {
        this.name = name;
        this._tables = new Set([VERSION_TABLE]);
        /**
         * Cached open connection, reused across operations instead of
         * reopening per read/write/invalidate. Dropped on a schema upgrade
         * (new table), a version-change request from another context, or
         * when the browser closes the connection.
         *
         * @type {IDBDatabase | null}
         */
        this._db = null;
        /**
         * Set when a blocked database deletion timed out (see
         * ``_deleteDatabase``): every subsequent operation short-circuits to
         * the no-db path (read → miss, write → no-op) for the session
         * instead of queueing behind the never-completing delete.
         */
        this._degraded = false;
        this.mutex = new Mutex();
        // Constructor can't be async, so this promise isn't awaited — but it
        // must be observed: ``_checkVersion`` -> ``_execute`` opens the DB
        // synchronously, which throws in private-browsing/storage-disabled
        // contexts. Swallow it; subsequent calls open their own connection
        // and degrade gracefully via their ``onerror`` arm.
        this.mutex.exec(() => this._checkVersion(version)).catch(() => {});
    }

    // -------------------------------------------------------------------------
    // Public
    // -------------------------------------------------------------------------

    /**
     * Reads data from a given table.
     *
     * @param {string} table
     * @param {string} key
     * @returns Promise
     */
    async read(table, key) {
        this._tables.add(table);
        return this.execute((db) => {
            if (db) {
                return this._read(db, table, key);
            }
        });
    }

    /**
     * Write data into the given table
     *
     * @param {string} table
     * @param {string} key
     * @param  {any} value
     * @returns Promise
     */
    async write(table, key, value) {
        this._tables.add(table);
        return this.execute((db) => {
            if (db) {
                return this._write(db, table, key, value);
            }
        });
    }

    /**
     * Invalidates a table, or the whole database.
     *
     * @param {string|string[]|null} [tables=null] if not given, the whole database is invalidated
     * @returns Promise
     */
    async invalidate(tables = null) {
        return this.execute((db) => {
            if (db) {
                return this._invalidate(
                    db,
                    typeof tables === "string" ? [tables] : tables,
                );
            }
        });
    }

    /**
     * Deletes entries from one or more tables via ``openKeyCursor``, keeping
     * only those for which ``predicate(key)`` is falsy. Used by the RPC
     * cache to scope ``CLEAR-CACHES`` invalidation without over-invalidating
     * unrelated models; O(N) per table. Predicate errors are swallowed
     * (entry kept) so one bad key can't abort the whole pass.
     *
     * @deprecated Production callers migrated to {@link invalidateByModel};
     *   kept for its regression tests covering a transaction-commit
     *   subtlety (no explicit ``commit()`` while cursors are pending).
     *
     * @param {string[]} tables
     * @param {(key: string) => boolean} predicate
     * @returns Promise
     */
    async invalidateWhere(tables, predicate) {
        return this.execute((db) => {
            if (db) {
                return this._invalidateWhere(db, tables, predicate);
            }
        });
    }

    /**
     * Deletes entries whose stored value has ``model === <model>``. Faster
     * than :meth:`invalidateWhere` for this common case: the predicate is a
     * fixed property check, and ``openCursor`` (not ``openKeyCursor``) is
     * used since the discriminator lives on the value — extra I/O but no
     * per-key parsing. Entries without a ``model`` property (e.g. written
     * before this migration) are silently kept; they stay reachable via
     * ``invalidate(table)`` but can't be scoped to a model.
     *
     * @param {string[]} tables
     * @param {string} model - Odoo model name, e.g. ``"res.partner"``
     * @returns Promise
     */
    async invalidateByModel(tables, model) {
        return this.execute((db) => {
            if (db) {
                return this._invalidateByModel(db, tables, model);
            }
        });
    }

    /**
     * Delete the whole database
     *
     * @returns Promise
     */
    async deleteDatabase() {
        return this.mutex.exec(() => this._deleteDatabase(() => {}));
    }

    /**
     * open the database and execute the callback with the db as parameter.
     *
     * @param {(db?: IDBDatabase) => any} callback
     * @returns Promise
     */
    async execute(callback) {
        return this.mutex.exec(() => this._execute(callback));
    }

    // -------------------------------------------------------------------------
    // Protected
    // -------------------------------------------------------------------------

    /**
     * Close and drop the cached connection (no-op when there is none).
     */
    _closeCachedDB() {
        if (this._db) {
            this._db.close();
            this._db = null;
        }
    }

    async _deleteDatabase(/** @type {() => any} */ callback) {
        // An open cached connection would block the deleteDatabase request.
        this._closeCachedDB();
        return new Promise((resolve) => {
            let settled = false;
            /** @type {any} */
            let blockedTimeoutId;
            const settle = (/** @type {boolean} */ runCallback) => {
                if (settled) {
                    return;
                }
                settled = true;
                browser.clearTimeout(blockedTimeoutId);
                if (runCallback) {
                    Promise.resolve(callback()).then(resolve);
                } else {
                    // Don't run the callback: it typically reopens the DB,
                    // and that open would queue behind the still-pending
                    // delete — the very hang we're escaping.
                    resolve(undefined);
                }
            };
            const request = indexedDB.deleteDatabase(this.name);
            request.onsuccess = () => settle(true);
            request.onerror = (event) => {
                console.error(
                    `IndexedDB delete error: ${/** @type {IDBRequest} */ (event.target).error?.message}`,
                );
                settle(true);
            };
            request.onblocked = () => {
                blockedTimeoutId = browser.setTimeout(() => {
                    console.warn(
                        `IndexedDB delete blocked: "${this.name}" is still open in another context ` +
                            `(e.g. a frozen tab); proceeding without cache for this session.`,
                    );
                    this._degraded = true;
                    settle(false);
                }, BLOCKED_DELETE_TIMEOUT);
            };
        });
    }

    async _checkVersion(/** @type {string} */ version) {
        const currentVersion = await this._execute((db) => {
            if (db) {
                return this._read(db, VERSION_TABLE, VERSION_KEY);
            }
        });
        if (!currentVersion) {
            await this._execute((db) => {
                if (db) {
                    return this._write(db, VERSION_TABLE, VERSION_KEY, version);
                }
            });
        } else if (currentVersion !== version) {
            await this._deleteDatabase(() =>
                this._execute((db) => {
                    if (db) {
                        return this._write(db, VERSION_TABLE, VERSION_KEY, version);
                    }
                }),
            );
        }
    }

    /**
     * Run the callback against an open connection, translating quota
     * errors. Extracted so the cached-connection fast path and the
     * fresh-open path share the exact same error handling.
     *
     * @param {IDBDatabase} db
     * @param {(db?: IDBDatabase) => any} callback
     */
    async _runCallback(db, callback) {
        try {
            return await callback(db);
        } catch (e) {
            if (e.name === "QuotaExceededError") {
                const { quota, usage } = await navigator.storage.estimate();
                console.error(
                    `IndexedDB error: Quota Exceeded (${formatStorageSize(
                        usage,
                    )} out of ${formatStorageSize(quota)} used)`,
                );
                throw new IDBQuotaExceededError();
            }
            throw e;
        }
    }

    /**
     * @param {(db?: IDBDatabase) => any} callback
     * @param {number} [idbVersion]
     */
    async _execute(callback, idbVersion) {
        if (this._degraded) {
            return callback();
        }
        // Fast path: reuse the cached connection when it already contains
        // every table this instance knows about (the common case once the
        // schema is warm). Runs under the same mutex as the open path, so
        // no schema-changing open can interleave with it.
        if (this._db && idbVersion === undefined) {
            const db = this._db;
            const dbTables = new Set(db.objectStoreNames);
            if (this._tables.difference(dbTables).size === 0) {
                try {
                    return await this._runCallback(db, callback);
                } catch (e) {
                    if (e?.name === "InvalidStateError") {
                        // The connection was closed under us (browser-initiated
                        // close, versionchange from another tab): drop the
                        // cached handle and retry with a fresh open.
                        if (this._db === db) {
                            this._db = null;
                        }
                        return this._execute(callback);
                    }
                    throw e;
                }
            }
            // A table is missing: close the cached connection so the open
            // below can perform the version-bump upgrade that creates it.
            this._closeCachedDB();
        }
        return new Promise((resolve, reject) => {
            let request;
            // ``onblocked`` guard, mirroring ``_deleteDatabase``: a
            // version-bump open (schema upgrade creating a missing table)
            // stays blocked as long as another context holds a connection to
            // the previous version — e.g. a frozen tab that never processes
            // its ``versionchange`` event. This runs inside the instance
            // mutex, so without the timeout every subsequent operation would
            // queue behind the never-completing open, forever.
            let settled = false;
            /** @type {any} */
            let blockedTimeoutId;
            const settle = (/** @type {() => void} */ fn) => {
                if (settled) {
                    return;
                }
                settled = true;
                browser.clearTimeout(blockedTimeoutId);
                fn();
            };
            try {
                request = indexedDB.open(this.name, idbVersion);
            } catch (e) {
                // ``indexedDB.open`` throws SYNCHRONOUSLY in storage-denied
                // contexts (private browsing, third-party-cookie-blocked
                // iframes). The async ``onerror`` arm below already degrades
                // to the no-db path; a sync throw must do the same instead of
                // rejecting the promise — boot-path consumers
                // (localization_service.start(), the RPC disk cache) await
                // reads unguarded, so a rejection here kills the webclient.
                console.warn(`IndexedDB unavailable: ${e?.message}`);
                this._degraded = true;
                Promise.resolve(callback()).then(resolve, reject);
                return;
            }
            request.onupgradeneeded = (event) => {
                const db = /** @type {IDBOpenDBRequest} */ (event.target).result;
                const dbTables = new Set(db.objectStoreNames);
                const newTables = this._tables.difference(dbTables);
                newTables.forEach((table) => db.createObjectStore(table));
            };
            request.onsuccess = (event) => {
                const db = /** @type {IDBOpenDBRequest} */ (event.target).result;
                if (settled) {
                    // The blocked-timeout already degraded this instance and
                    // settled the promise; the open finally completed once
                    // the blocking context went away. Close the late
                    // connection immediately so it can't in turn block other
                    // contexts' upgrades or deletes.
                    db.close();
                    return;
                }
                settle(() => {
                    const dbTables = new Set(db.objectStoreNames);
                    const newTables = this._tables.difference(dbTables);
                    if (newTables.size !== 0) {
                        db.close();
                        const version = db.version + 1;
                        // Forward BOTH arms: a failing version-bump upgrade
                        // (e.g. the ``onupgradeneeded`` transaction aborts)
                        // must reject this promise, not leave it pending
                        // forever with an unhandled rejection dangling off
                        // the inner ``_execute``.
                        this._execute(callback, version).then(resolve, reject);
                        return;
                    }
                    // Cache the connection for subsequent operations. Drop
                    // (and close) it as soon as another context requests a
                    // version change — keeping it open would block that
                    // upgrade — or when the browser closes the connection
                    // itself.
                    this._db = db;
                    db.onversionchange = () => {
                        db.close();
                        if (this._db === db) {
                            this._db = null;
                        }
                    };
                    db.onclose = () => {
                        if (this._db === db) {
                            this._db = null;
                        }
                    };
                    this._runCallback(db, callback).then(resolve, reject);
                });
            };
            request.onerror = (event) => {
                settle(() => {
                    console.error(
                        `IndexedDB error: ${/** @type {IDBRequest} */ (event.target).error?.message}`,
                    );
                    Promise.resolve(callback()).then(resolve);
                });
            };
            request.onblocked = () => {
                blockedTimeoutId = browser.setTimeout(() => {
                    console.warn(
                        `IndexedDB upgrade blocked: "${this.name}" is still open in another context ` +
                            `(e.g. a frozen tab); proceeding without cache for this session.`,
                    );
                    this._degraded = true;
                    settle(() => Promise.resolve(callback()).then(resolve, reject));
                }, BLOCKED_DELETE_TIMEOUT);
            };
        });
    }

    async _write(
        /** @type {IDBDatabase} */ db,
        /** @type {string} */ table,
        /** @type {string} */ key,
        /** @type {any} */ record,
    ) {
        return new Promise((resolve, reject) => {
            // AAB: do we care about write performance?
            // Relaxed durability improves the write performances
            // https://nolanlawson.com/2021/08/22/speeding-up-indexeddb-reads-and-writes/
            // https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction/durability
            const transaction = db.transaction(table, "readwrite", {
                durability: "relaxed",
            });
            transaction.objectStore(table).put(record, key); // put to allow updates
            transaction.onerror = (ev) =>
                reject(/** @type {IDBTransaction} */ (ev.target).error); // firefox (DOMException)
            transaction.onabort = (ev) =>
                reject(/** @type {IDBTransaction} */ (ev.target).error); // chrome (QuotaExceededError)
            transaction.oncomplete = resolve;

            // Force the changes to be committed to the database asap
            // https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction/commit
            transaction.commit();
        });
    }

    async _invalidate(
        /** @type {IDBDatabase} */ db,
        /** @type {string[] | null} */ tables,
    ) {
        return new Promise((resolve, reject) => {
            const objectStoreNames = [...db.objectStoreNames].filter(
                (table) => table !== VERSION_TABLE,
            );
            tables = tables
                ? objectStoreNames.filter((t) => tables.includes(t))
                : objectStoreNames;

            if (!tables.length) {
                return resolve(undefined);
            }
            // Relaxed durability improves the write performances
            // https://nolanlawson.com/2021/08/22/speeding-up-indexeddb-reads-and-writes/
            // https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction/durability
            const transaction = db.transaction(tables, "readwrite", {
                durability: "relaxed",
            });
            const proms = tables.map(
                (table) =>
                    new Promise((resolve) => {
                        const objectStore = transaction.objectStore(table);
                        const request = objectStore.clear();
                        request.onsuccess = resolve;
                    }),
            );
            transaction.onerror = () => reject(transaction.error);
            // Without an ``onabort`` arm an aborted transaction (e.g. quota
            // exceeded) settles neither handler and the promise stays
            // pending forever, wedging the instance mutex.
            transaction.onabort = () => reject(transaction.error);
            Promise.all(proms).then(resolve);

            // Force the changes to be committed to the database asap
            // https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction/commit
            transaction.commit();
        });
    }

    async _read(
        /** @type {IDBDatabase} */ db,
        /** @type {string} */ table,
        /** @type {string} */ key,
    ) {
        return new Promise((resolve, reject) => {
            const transaction = db.transaction(table, "readonly");
            const objectStore = transaction.objectStore(table);
            const r = objectStore.get(key);
            r.onsuccess = () => resolve(r.result);
            transaction.onerror = () => reject(transaction.error);
            // See ``_invalidate``: an aborted transaction fires neither
            // ``onsuccess`` nor ``onerror`` — reject instead of leaving the
            // promise (and the instance mutex) pending forever.
            transaction.onabort = () => reject(transaction.error);
        });
    }

    async _invalidateByModel(
        /** @type {IDBDatabase} */ db,
        /** @type {string[]} */ tables,
        /** @type {string} */ model,
    ) {
        return new Promise((resolve, reject) => {
            const objectStoreNames = [...db.objectStoreNames].filter(
                (table) => table !== VERSION_TABLE,
            );
            const targetTables = objectStoreNames.filter((t) => tables.includes(t));
            if (!targetTables.length) {
                return resolve(undefined);
            }
            const transaction = db.transaction(targetTables, "readwrite", {
                durability: "relaxed",
            });
            transaction.oncomplete = () => resolve(undefined);
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(transaction.error);
            for (const table of targetTables) {
                const objectStore = transaction.objectStore(table);
                // ``openCursor`` reads ``cursor.value.model`` (see docblock
                // above); entries without ``model`` are kept as-is.
                const request = objectStore.openCursor();
                request.onsuccess = (event) => {
                    const cursor = /** @type {IDBCursorWithValue | null} */ (
                        /** @type {IDBRequest} */ (event.target).result
                    );
                    if (!cursor) {
                        return;
                    }
                    if (cursor.value?.model === model) {
                        objectStore.delete(cursor.key);
                    }
                    cursor.continue();
                };
            }
        });
    }

    async _invalidateWhere(
        /** @type {IDBDatabase} */ db,
        /** @type {string[]} */ tables,
        /** @type {(key: string) => boolean} */ predicate,
    ) {
        return new Promise((resolve, reject) => {
            const objectStoreNames = [...db.objectStoreNames].filter(
                (table) => table !== VERSION_TABLE,
            );
            const targetTables = objectStoreNames.filter((t) => tables.includes(t));
            if (!targetTables.length) {
                return resolve(undefined);
            }
            // Relaxed durability matches sibling write paths; the
            // cursor iteration runs inside the single transaction so
            // either every targeted entry is deleted or none is.
            const transaction = db.transaction(targetTables, "readwrite", {
                durability: "relaxed",
            });
            // ``oncomplete`` fires only once every queued request (cursor
            // continuations, ``delete(key)`` writes) has landed; wired
            // before opening cursors so the handlers exist when it fires.
            transaction.oncomplete = () => resolve(undefined);
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(transaction.error);
            for (const table of targetTables) {
                // Keep a store reference: ``openKeyCursor`` yields a
                // key-only ``IDBCursor`` with no ``.delete()`` (reserved for
                // value cursors), so delete via the store by explicit key.
                const objectStore = transaction.objectStore(table);
                const request = objectStore.openKeyCursor();
                request.onsuccess = (event) => {
                    const cursor = /** @type {IDBCursor | null} */ (
                        /** @type {IDBRequest} */ (event.target).result
                    );
                    if (!cursor) {
                        // Exhausted; the transaction auto-commits once every
                        // table's cursor reaches this branch.
                        return;
                    }
                    let shouldDelete = false;
                    try {
                        shouldDelete = predicate(/** @type {string} */ (cursor.key));
                    } catch {
                        // Predicate error: treat as non-matching, keep the entry.
                    }
                    if (shouldDelete) {
                        objectStore.delete(cursor.key);
                    }
                    cursor.continue();
                };
            }
            // No explicit ``commit()``: cursor iteration queues one
            // ``continue()`` per tick, and committing while requests are
            // pending would make the next ``continue()`` raise
            // ``TransactionInactiveError``. Auto-commits once every cursor
            // exhausts.
        });
    }
}
