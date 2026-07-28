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
        this.mutex.exec(() => this._checkVersion(version)).catch(() => {});
    }

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
        if (this._db && idbVersion === undefined) {
            const db = this._db;
            const dbTables = new Set(db.objectStoreNames);
            if (this._tables.difference(dbTables).size === 0) {
                try {
                    return await this._runCallback(db, callback);
                } catch (e) {
                    if (e?.name === "InvalidStateError") {
                        if (this._db === db) {
                            this._db = null;
                        }
                        return this._execute(callback);
                    }
                    throw e;
                }
            }
            this._closeCachedDB();
        }
        return new Promise((resolve, reject) => {
            let request;
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
                    db.close();
                    return;
                }
                settle(() => {
                    const dbTables = new Set(db.objectStoreNames);
                    const newTables = this._tables.difference(dbTables);
                    if (newTables.size !== 0) {
                        db.close();
                        const version = db.version + 1;
                        this._execute(callback, version).then(resolve, reject);
                        return;
                    }
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
            const transaction = db.transaction(table, "readwrite", {
                durability: "relaxed",
            });
            transaction.objectStore(table).put(record, key);
            transaction.onerror = (ev) =>
                reject(/** @type {IDBTransaction} */ (ev.target).error);
            transaction.onabort = (ev) =>
                reject(/** @type {IDBTransaction} */ (ev.target).error);
            transaction.oncomplete = resolve;

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
            transaction.onabort = () => reject(transaction.error);
            Promise.all(proms).then(resolve);

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
            const transaction = db.transaction(targetTables, "readwrite", {
                durability: "relaxed",
            });
            transaction.oncomplete = () => resolve(undefined);
            transaction.onerror = () => reject(transaction.error);
            transaction.onabort = () => reject(transaction.error);
            for (const table of targetTables) {
                const objectStore = transaction.objectStore(table);
                const request = objectStore.openKeyCursor();
                request.onsuccess = (event) => {
                    const cursor = /** @type {IDBCursor | null} */ (
                        /** @type {IDBRequest} */ (event.target).result
                    );
                    if (!cursor) {
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
        });
    }
}
