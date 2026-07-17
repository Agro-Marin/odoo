/** @odoo-module native */
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/ui/dialog/confirmation_dialog";

const BATCH_SIZE = 500; // Can be adjusted based on performance testing
const TRANSACTION_TIMEOUT = 5000; // 5 seconds timeout for transactions
const CONSOLE_COLOR = "#3ba9ff";

export default class IndexedDB {
    constructor(dbName, dbVersion, dbStores, whenReady, dialog = null) {
        this.db = null;
        this.dbName = dbName;
        this.dbVersion = dbVersion;
        this.dbStores = dbStores;
        this.dbInstance = null;
        this.activeTransactions = new Set();
        this.dialog = dialog;
        this._isReconnecting = false;
        this._reloadDialogShown = false;
        this.databaseEventListener(whenReady);
    }

    databaseEventListener(whenReady) {
        const indexedDB =
            window.indexedDB ||
            window.mozIndexedDB ||
            window.webkitIndexedDB ||
            window.msIndexedDB;

        if (!indexedDB) {
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                "Your browser does not support IndexedDB. Data will not be saved.",
                CONSOLE_COLOR,
            );
        }

        this.dbInstance = indexedDB;
        let dbInstance;
        if (this.dbVersion) {
            dbInstance = indexedDB.open(this.dbName, this.dbVersion);
        } else {
            dbInstance = indexedDB.open(this.dbName);
        }
        dbInstance.onerror = (event) => {
            const err = event.target.error;
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                `Error opening IndexedDB: ${err?.message || event.target.errorCode}`,
                CONSOLE_COLOR,
            );
            // Known iOS/Safari WebKit bug: the IDB server process was killed
            // by the OS. No reconnect will succeed — only a page reload
            // restores the daemon (upstream 00da82dbb99).
            if (err?.message?.includes("Connection to Indexed Database server lost")) {
                this._showReloadDialog();
            }
        };
        dbInstance.onblocked = () => {
            // A versioned reopen (schema upgrade) is blocked by another tab
            // holding the database open. Without this handler the open request
            // waited forever and the whole POS hung on a blank loader.
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                "IndexedDB upgrade blocked by another open POS tab — close other tabs of this POS.",
                CONSOLE_COLOR,
            );
        };
        dbInstance.onsuccess = (event) => {
            this.db = event.target.result;
            // Yield to schema upgrades initiated by another (newer) tab, so a
            // versioned reopen there is never blocked by this connection.
            // Then reconnect: without this the connection stayed null forever
            // (getNewTransaction's `!this.db` branch neither reconnects nor
            // warns), so every subsequent read/write silently no-op'd and the
            // tab traded on with local persistence permanently dead. The
            // reconnect is deferred so the upgrading tab finishes first.
            this.db.onversionchange = () => {
                this.db?.close();
                this.db = null;
                this._attemptReconnect();
            };

            const actualStoreNames = this.db.objectStoreNames;
            let needsUpgrade = false;

            for (const [, storeName] of this.dbStores) {
                if (!actualStoreNames.contains(storeName)) {
                    logPosMessage(
                        "IndexedDB",
                        "onsuccess",
                        `Schema mismatch: Store '${storeName}' is missing. Triggering upgrade.`,
                        CONSOLE_COLOR,
                    );
                    needsUpgrade = true;
                    break;
                }
            }

            if (needsUpgrade) {
                const newVersion = this.db.version + 1;
                this.db.close();
                this.dbVersion = newVersion;

                logPosMessage(
                    "IndexedDB",
                    "onsuccess",
                    `Upgrading from v${newVersion - 1} to v${newVersion}...`,
                    CONSOLE_COLOR,
                );

                this.databaseEventListener(whenReady);
                return;
            }

            this._setupVisibilityProbe();
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                `IndexedDB ${this.dbName} Ready`,
                CONSOLE_COLOR,
            );
            whenReady?.();
        };
        dbInstance.onupgradeneeded = (event) => {
            for (const [id, storeName] of this.dbStores) {
                if (!event.target.result.objectStoreNames.contains(storeName)) {
                    event.target.result.createObjectStore(storeName, { keyPath: id });
                }
            }
        };
    }

    async promises(storeName, arrData, method) {
        if (!arrData?.length) {
            return;
        }

        // Batch processing for large arrays to avoid performance issues
        // or transaction failures due to large data sets
        const results = [];
        for (let i = 0; i < arrData.length; i += BATCH_SIZE) {
            let timeoutId;
            let finished = false;

            const batch = arrData.slice(i, i + BATCH_SIZE);
            const transaction = this.getNewTransaction([storeName], "readwrite");

            if (!transaction) {
                // A raw rejected Promise in the results array is never awaited
                // by any caller — it only produced an unhandledrejection.
                results.push({
                    status: "rejected",
                    reason: "Transaction could not be created",
                });
                continue;
            }

            const doneMethod = () => {
                finished = true;
                clearTimeout(timeoutId);
                this.activeTransactions.delete(transaction);
            };

            // Mark transaction as finished in all cases
            transaction.oncomplete = doneMethod;
            transaction.onabort = doneMethod;
            transaction.onerror = doneMethod;
            transaction.onsuccess = doneMethod;

            const batchPromise = new Promise((resolve, reject) => {
                const store = transaction.objectStore(storeName);
                let completed = 0;
                let hasError = false;

                timeoutId = setTimeout(() => {
                    if (!finished) {
                        reject(new Error("IndexedDB transaction timeout"));
                        try {
                            transaction.abort();
                        } catch (e) {
                            logPosMessage(
                                "IndexedDB",
                                method,
                                `Error aborting transaction: ${e.message}`,
                                CONSOLE_COLOR,
                            );
                        }
                    }
                }, TRANSACTION_TIMEOUT);

                logPosMessage(
                    "IndexedDB",
                    method,
                    `Processing ${batch.length} items in store ${storeName}`,
                    CONSOLE_COLOR,
                );

                for (const data of batch) {
                    try {
                        const deepCloned = JSON.parse(JSON.stringify(data));
                        const request = store[method](deepCloned);

                        request.onsuccess = () => {
                            completed++;
                            if (completed === batch.length && !hasError && !finished) {
                                clearTimeout(timeoutId);
                                resolve();
                            }
                        };

                        request.onerror = (event) => {
                            hasError = true;
                            clearTimeout(timeoutId);
                            logPosMessage(
                                "IndexedDB",
                                method,
                                `Error processing ${method} for ${storeName}: ${event.target?.error}`,
                                CONSOLE_COLOR,
                            );
                            reject(event.target?.error || "Unknown error");
                        };
                    } catch {
                        // Count the unserializable item as processed so a single bad
                        // record can't stall the whole batch until TRANSACTION_TIMEOUT
                        // fires and aborts (rolling back every successful put in it).
                        completed++;
                        logPosMessage(
                            "IndexedDB",
                            method,
                            `Error processing ${method} for ${storeName}: Invalid data format`,
                            CONSOLE_COLOR,
                        );
                        if (completed === batch.length && !hasError && !finished) {
                            clearTimeout(timeoutId);
                            resolve();
                        }
                    }
                }
            });

            const result = await batchPromise
                .then(() => ({ status: "fulfilled" }))
                .catch((err) => ({ status: "rejected", reason: err }));
            results.push(result);
        }

        return results;
    }

    getNewTransaction(dbStore, mode = "readwrite") {
        try {
            if (!this.db) {
                return false;
            }

            const transaction = this.db.transaction(dbStore, mode);
            this.activeTransactions.add(transaction);
            return transaction;
        } catch (e) {
            logPosMessage(
                "IndexedDB",
                "getNewTransaction",
                `Error creating transaction: ${e.message}`,
                CONSOLE_COLOR,
            );
            if (e.name === "InvalidStateError") {
                // The connection silently died (iOS backgrounding): drop it
                // and try to reconnect.
                this.db = null;
                this._attemptReconnect();
            }
            return false;
        }
    }

    _attemptReconnect() {
        if (this._isReconnecting) {
            return;
        }
        this._isReconnecting = true;
        if (this.db) {
            try {
                this.db.close();
            } catch {
                // already closed
            }
            this.db = null;
        }
        setTimeout(() => {
            this.databaseEventListener(() => {
                this._isReconnecting = false;
            });
        }, 3000);
    }

    _setupVisibilityProbe() {
        if (this._visibilityProbeAttached) {
            return;
        }
        this._visibilityProbeAttached = true;
        // iOS/Safari can kill the IDB server while the tab is backgrounded:
        // probe the connection when the tab becomes visible again.
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState !== "visible" || !this.db) {
                return;
            }
            try {
                this.db.transaction([this.dbStores[0][1]], "readonly").abort();
            } catch {
                this.db = null;
                this._attemptReconnect();
            }
        });
    }

    _showReloadDialog() {
        if (!this.dialog || this._reloadDialogShown) {
            return;
        }
        this._reloadDialogShown = true;
        this.dialog.add(AlertDialog, {
            title: _t("Database Connection Lost"),
            body: _t(
                "The connection to the local database was lost. Reloading the page will restore it and prevent any loss of unsaved orders.",
            ),
            confirmLabel: _t("Reload"),
            confirm: () => window.location.reload(),
        });
    }

    reset() {
        return new Promise((resolve) => {
            if (this.db) {
                this.db.close();
            }

            if (!this.dbInstance) {
                return resolve(true);
            }

            const timeout = setTimeout(() => {
                logPosMessage(
                    "IndexedDB",
                    "reset",
                    "Timeout: Database reset took too long",
                    CONSOLE_COLOR,
                );
                resolve(false);
            }, 3000);

            const request = this.dbInstance.deleteDatabase(this.dbName);

            request.onsuccess = () => {
                logPosMessage(
                    "IndexedDB",
                    "reset",
                    "Database deleted successfully",
                    CONSOLE_COLOR,
                );
                this.db = null;
                clearTimeout(timeout);
                resolve(true);
            };

            request.onerror = (event) => {
                logPosMessage(
                    "IndexedDB",
                    "reset",
                    `Error deleting DB: ${event.target.error}`,
                    CONSOLE_COLOR,
                );
                clearTimeout(timeout);
                resolve(false);
            };

            request.onblocked = () => {
                logPosMessage(
                    "IndexedDB",
                    "reset",
                    "Blocked deleting DB",
                    CONSOLE_COLOR,
                );
                clearTimeout(timeout);
                resolve(false);
            };
        });
    }

    create(storeName, arrData) {
        if (!arrData?.length) {
            return;
        }
        return this.promises(storeName, arrData, "put");
    }

    readAll(store = []) {
        const storeNames =
            store.length > 0 ? store : this.dbStores.map((store) => store[1]);
        const transaction = this.getNewTransaction(storeNames, "readonly");

        if (!transaction) {
            // NB: the synchronous 5x retry that used to sit here was a no-op
            // (nothing changes between two synchronous attempts), and
            // `new Promise((reject) => reject(false))` actually RESOLVED with
            // false — callers survived by accident. Keep that contract
            // explicitly.
            return Promise.resolve(false);
        }

        const removeTransaction = () => {
            this.activeTransactions.delete(transaction);
        };

        transaction.oncomplete = removeTransaction;
        transaction.onabort = removeTransaction;
        transaction.onerror = removeTransaction;
        transaction.onsuccess = removeTransaction;

        const promises = storeNames.map(
            (store) =>
                new Promise((resolve, reject) => {
                    const objectStore = transaction.objectStore(store);
                    const request = objectStore.getAll();

                    const errorMethod = (event) => {
                        logPosMessage(
                            "IndexedDB",
                            "readAll",
                            `Error reading data from store ${store}: ${event.target.error}`,
                            CONSOLE_COLOR,
                        );
                        reject(event.target.error || "Unknown error");
                    };

                    const successMethod = (event) => {
                        const result = event.target.result;
                        resolve({ [store]: result });
                    };

                    request.onerror = errorMethod;
                    request.onabort = errorMethod;
                    request.onsuccess = successMethod;
                }),
        );

        return Promise.allSettled(promises).then((results) =>
            results.reduce((acc, result) => {
                if (result.status === "fulfilled") {
                    return { ...acc, ...result.value };
                } else {
                    return acc;
                }
            }, {}),
        );
    }

    delete(storeName, uuids) {
        if (!uuids?.length) {
            return;
        }
        return this.promises(storeName, uuids, "delete");
    }
}
