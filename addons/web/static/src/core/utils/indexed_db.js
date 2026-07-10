// @ts-check
/** @odoo-module native */

/** @module @web/core/utils/indexed_db - IndexedDB wrapper with versioned schema, quota management, and mutex locking */

import { Mutex } from "./concurrency.js";

const VERSION_TABLE = "__DBVersion__";
const VERSION_KEY = "__version__";

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
         * opening (and closing) a fresh one per read/write/invalidate.
         * Dropped when a schema upgrade is needed (new table), when
         * another context requests a version change, or when the browser
         * closes the connection.
         *
         * @type {IDBDatabase | null}
         */
        this._db = null;
        this.mutex = new Mutex();
        // The returned promise is intentionally not awaited (the constructor
        // can't be async), but it must still be observed: ``_checkVersion`` ->
        // ``_execute`` calls ``indexedDB.open`` synchronously, which THROWS in
        // private-browsing / storage-disabled contexts.  Without this catch
        // that throw surfaces as an unhandled promise rejection.  Swallow it
        // here — subsequent read/write/invalidate calls each open their own
        // connection and degrade gracefully (their ``onerror`` arm resolves).
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
     * Selectively delete entries from one or more tables.  Iterates each
     * table's keys with an ``openKeyCursor`` and deletes only those for
     * which ``predicate(key)`` returns ``true``.
     *
     * Used by the RPC cache to honour model-scoped ``CLEAR-CACHES``
     * signals on the disk cache without over-invalidating unrelated
     * models.  The cursor scan is O(N) per table but avoids the
     * "blow away everything on any unlink" footgun of plain
     * :meth:`invalidate`.
     *
     * Predicate errors are swallowed (a malformed key is treated as
     * non-matching and left in place) so a single bad entry can't
     * abort the entire invalidation pass.
     *
     * @deprecated Production callers migrated to {@link invalidateByModel};
     *   kept because its regression tests document a transaction-commit
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
     * Delete entries whose stored value carries ``model === <model>``.
     *
     * Faster path than :meth:`invalidateWhere` for the canonical
     * "invalidate one Odoo model's cached responses" case: the predicate
     * is a fixed object-property check, so the cursor never has to invoke
     * a caller-supplied function or JSON.parse the key.  ``openCursor`` is
     * used (vs ``openKeyCursor``) because the discriminator lives on the
     * stored value (``cursor.value.model``); this trades a little extra
     * I/O for value reads against eliminating per-key parse cost — net
     * win for typical entry sizes.
     *
     * Entries written without a ``model`` property are silently kept
     * (correct — they are not model-scoped). This includes pre-existing
     * entries written by older code before the model-on-value migration;
     * they remain accessible to ``invalidate(table)`` but cannot be
     * surgically scoped to a model.
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
            const request = indexedDB.deleteDatabase(this.name);
            request.onsuccess = () => {
                Promise.resolve(callback()).then(resolve);
            };
            request.onerror = (event) => {
                console.error(
                    `IndexedDB delete error: ${/** @type {IDBRequest} */ (event.target).error?.message}`,
                );
                Promise.resolve(callback()).then(resolve);
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
            const request = indexedDB.open(this.name, idbVersion);
            request.onupgradeneeded = (event) => {
                const db = /** @type {IDBOpenDBRequest} */ (event.target).result;
                const dbTables = new Set(db.objectStoreNames);
                const newTables = this._tables.difference(dbTables);
                newTables.forEach((table) => db.createObjectStore(table));
            };
            request.onsuccess = (event) => {
                const db = /** @type {IDBOpenDBRequest} */ (event.target).result;
                const dbTables = new Set(db.objectStoreNames);
                const newTables = this._tables.difference(dbTables);
                if (newTables.size !== 0) {
                    db.close();
                    const version = db.version + 1;
                    // Forward BOTH arms: a failing version-bump upgrade (e.g.
                    // the ``onupgradeneeded`` transaction aborts) must reject
                    // this promise, not leave it pending forever with an
                    // unhandled rejection dangling off the inner ``_execute``.
                    return this._execute(callback, version).then(resolve, reject);
                }
                // Cache the connection for subsequent operations. Drop (and
                // close) it as soon as another context requests a version
                // change — keeping it open would block that upgrade — or
                // when the browser closes the connection itself.
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
            };
            request.onerror = (event) => {
                console.error(
                    `IndexedDB error: ${/** @type {IDBRequest} */ (event.target).error?.message}`,
                );
                Promise.resolve(callback()).then(resolve);
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
                // ``openCursor`` (not ``openKeyCursor``) so we can read
                // ``cursor.value.model``. The value is materialised but
                // the per-step cost — object property access — beats the
                // predicate cost of the prior ``invalidateWhere`` path
                // which JSON.parsed each key.  Old entries without a
                // ``model`` property are silently kept.
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
            // ``oncomplete`` is the canonical resolve signal: it fires
            // after every queued request (cursor continuations and the
            // store ``delete(key)`` writes below) has landed durably.
            // Wire it before opening cursors so the handlers exist when
            // the transaction enters its terminal state.
            transaction.oncomplete = () => resolve(undefined);
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(transaction.error);
            for (const table of targetTables) {
                // Keep a reference to the store: ``openKeyCursor`` returns
                // an ``IDBCursor`` (key-only) which cannot call its own
                // ``.delete()`` — that method is reserved for value
                // cursors from ``openCursor``. Deleting through the
                // object store by explicit key is both spec-compliant
                // and cheaper (we never materialise the value).
                const objectStore = transaction.objectStore(table);
                const request = objectStore.openKeyCursor();
                request.onsuccess = (event) => {
                    const cursor = /** @type {IDBCursor | null} */ (
                        /** @type {IDBRequest} */ (event.target).result
                    );
                    if (!cursor) {
                        // Cursor exhausted for this table; nothing more
                        // to queue. The transaction auto-commits once
                        // every table's cursor reaches this branch.
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
            // No explicit ``transaction.commit()``: cursor iteration
            // queues one ``continue()`` per onsuccess tick, and calling
            // ``commit()`` while requests are still pending moves the
            // transaction to the committing state, causing the next
            // ``cursor.continue()`` to raise ``TransactionInactiveError``.
            // The transaction auto-commits when every cursor exhausts.
        });
    }
}
