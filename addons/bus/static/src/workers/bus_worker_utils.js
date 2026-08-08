/** @odoo-module native */
/**
 * Returns a function, that, as long as it continues to be invoked, will not
 * be triggered. The function will be called after it stops being called for
 * N milliseconds (trailing edge only — a leading-edge `immediate` variant
 * used to exist here but had no callers).
 *
 * Inspired by https://davidwalsh.name/javascript-debounce-function
 */
export function debounce(func, wait) {
    let timeout;
    function debounced() {
        const context = this;
        const args = arguments;
        clearTimeout(timeout);
        timeout = setTimeout(() => {
            timeout = null;
            func.apply(context, args);
        }, wait);
    }
    // Cancel a pending trailing invocation. Needed so a lifecycle reset (e.g.
    // the worker's `_stop()`) can drop an in-flight debounced `subscribe`/send
    // instead of letting it fire against the next connection.
    debounced.cancel = function () {
        clearTimeout(timeout);
        timeout = null;
    };
    return debounced;
}

/**
 * Deferred is basically a resolvable/rejectable extension of Promise.
 */
export class Deferred extends Promise {
    constructor() {
        let resolve;
        let reject;
        const prom = new Promise((res, rej) => {
            resolve = res;
            reject = rej;
        });
        return Object.assign(prom, { resolve, reject });
    }
}

export class Logger {
    static LOG_TTL = 24 * 60 * 60 * 1000; // 24 hours
    static gcInterval = null;
    static instances = [];
    _db;

    static async gcOutdatedLogs() {
        const threshold = Date.now() - Logger.LOG_TTL;
        for (const logger of this.instances) {
            if (!logger._db && !logger._dbPromise) {
                // Never opened this session: don't open IndexedDB just to
                // garbage-collect. Leftover logs from a previous session are
                // pruned the next time this logger is actually used
                // (`getLogs` opens the database before GC'ing).
                continue;
            }
            try {
                await logger._ensureDatabaseAvailable();
                await new Promise((res, rej) => {
                    const transaction = logger._db.transaction("logs", "readwrite");
                    const store = transaction.objectStore("logs");
                    const req = store
                        .index("timestamp")
                        .openCursor(IDBKeyRange.upperBound(threshold));
                    req.onsuccess = (event) => {
                        const cursor = event.target.result;
                        if (cursor) {
                            cursor.delete();
                            cursor.continue();
                        }
                    };
                    req.onerror = (e) => rej(e.target.error);
                    transaction.oncomplete = res;
                    transaction.onerror = (e) => rej(e.target.error);
                });
            } catch (error) {
                // Includes a synchronous throw from `transaction()` on a handle
                // that died since it was cached: drop it so the next use
                // reopens instead of failing every GC pass from here on.
                logger._forgetDatabase();
                console.error(
                    `Failed to clear logs for logger "${logger._name}":`,
                    error,
                );
            }
        }
    }

    constructor(name) {
        this._name = name;
        Logger.instances.push(this);
        // Deliberately no IndexedDB access here: a Logger is created on every
        // worker boot (module level in websocket_worker.js) even when logging
        // is disabled. The database is only opened on the first `log()` /
        // `getLogs()`, and garbage collection runs lazily from there.
    }

    /** Arm the periodic GC once a database is actually in use. */
    static _ensureGcScheduled() {
        Logger.gcInterval ??= setInterval(
            () => Logger.gcOutdatedLogs(),
            Logger.LOG_TTL,
        );
    }

    /**
     * Drop the cached connection so the next call reopens it.
     *
     * An IDBDatabase handle can stop being usable without this object hearing
     * about it (the browser closing it under storage pressure, "clear site
     * data", a `versionchange` from another context). `_ensureDatabaseAvailable`
     * short-circuits on `this._db`, so a stale handle would otherwise be reused
     * forever and every later `transaction()` would throw InvalidStateError for
     * the rest of the worker's life -- silently killing bus logging, since
     * `_logDebug` swallows the rejection into a console error.
     */
    _forgetDatabase() {
        this._db = null;
        this._dbPromise = null;
    }

    async _ensureDatabaseAvailable() {
        if (this._db) {
            return;
        }
        // Dedupe concurrent opens: `log()`/`getLogs()`/`gcOutdatedLogs()` can
        // all race here before `_db` is set. Without this, each call issues its
        // own `indexedDB.open`, and multiple in-flight opens interleave with
        // `onupgradeneeded`. Cache the single in-flight open promise instead.
        this._dbPromise ??= new Promise((res, rej) => {
            const request = indexedDB.open(this._name, 1);
            request.onsuccess = (event) => {
                this._db = event.target.result;
                // Abnormal closure (storage pressure, "clear site data", ...):
                // the handle is dead, forget it so the next call reopens.
                this._db.onclose = () => this._forgetDatabase();
                // Another context wants to upgrade: we must close, or we block
                // it indefinitely. Same recovery on the next call.
                this._db.onversionchange = () => {
                    this._db?.close();
                    this._forgetDatabase();
                };
                res();
            };
            request.onupgradeneeded = (event) => {
                if (!event.target.result.objectStoreNames.contains("logs")) {
                    const store = event.target.result.createObjectStore("logs", {
                        autoIncrement: true,
                    });
                    store.createIndex("timestamp", "timestamp", { unique: false });
                }
            };
            request.onerror = (e) => {
                // Allow a later call to retry the open.
                this._forgetDatabase();
                rej(e.target.error);
            };
        });
        return this._dbPromise;
    }

    async log(message) {
        await this._ensureDatabaseAvailable();
        Logger._ensureGcScheduled();
        let transaction;
        try {
            transaction = this._db.transaction("logs", "readwrite");
        } catch (error) {
            // The handle died after `_ensureDatabaseAvailable` cleared us (the
            // `close` event may not have been delivered yet). Forget it so the
            // next call reopens rather than throwing for the rest of the
            // session.
            this._forgetDatabase();
            throw error;
        }
        const store = transaction.objectStore("logs");
        const addRequest = store.add({ timestamp: Date.now(), message });
        return new Promise((res, rej) => {
            addRequest.onsuccess = res;
            addRequest.onerror = (e) => rej(e.target.error);
        });
    }

    async getLogs() {
        // Open before GC'ing: `gcOutdatedLogs` skips loggers with no open
        // database, and returned logs must not include expired entries.
        await this._ensureDatabaseAvailable();
        Logger._ensureGcScheduled();
        await Logger.gcOutdatedLogs();
        const transaction = this._db.transaction("logs", "readonly");
        const store = transaction.objectStore("logs");
        const request = store.getAll();
        return new Promise((res, rej) => {
            request.onsuccess = (ev) =>
                res(ev.target.result.map(({ message }) => message));
            request.onerror = (e) => rej(e.target.error);
        });
    }
}
