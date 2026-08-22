/** @odoo-module native */
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { _t } from "@web/core/translation";
import { AlertDialog } from "@web/ui/dialog";

const BATCH_SIZE = 500;
const TRANSACTION_TIMEOUT = 5000;
const CONSOLE_COLOR = "#3ba9ff";
const RECONNECT_BASE_DELAY = 3000;
const RECONNECT_MAX_DELAY = 60000;
const MAX_RECONNECT_ATTEMPTS = 5;
const OPEN_BLOCKED_TIMEOUT = 10000;

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
        this._reconnectAttempts = 0;
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
        let settled = false;
        const openFailed = (reason) => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(blockedTimeoutId);
            this._openFailed(reason);
        };
        let blockedTimeoutId;

        dbInstance.onerror = (event) => {
            const err = event.target.error;
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                `Error opening IndexedDB: ${err?.message || event.target.errorCode}`,
                CONSOLE_COLOR,
            );
            if (err?.message?.includes("Connection to Indexed Database server lost")) {
                settled = true;
                clearTimeout(blockedTimeoutId);
                this._isReconnecting = false;
                this._showReloadDialog();
                return;
            }
            openFailed(err?.message || "open failed");
        };
        dbInstance.onblocked = () => {
            logPosMessage(
                "IndexedDB",
                "databaseEventListener",
                "IndexedDB upgrade blocked by another open POS tab — close other tabs of this POS.",
                CONSOLE_COLOR,
            );
            blockedTimeoutId = setTimeout(
                () => openFailed("open blocked by another tab"),
                OPEN_BLOCKED_TIMEOUT,
            );
        };
        dbInstance.onsuccess = (event) => {
            if (settled) {
                event.target.result.close();
                return;
            }
            settled = true;
            clearTimeout(blockedTimeoutId);
            this.db = event.target.result;
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

            this._isReconnecting = false;
            this._reconnectAttempts = 0;
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

        const results = [];
        for (let i = 0; i < arrData.length; i += BATCH_SIZE) {
            let timeoutId;
            let finished = false;

            const batch = arrData.slice(i, i + BATCH_SIZE);
            const transaction = this.getNewTransaction([storeName], "readwrite");

            if (!transaction) {
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

            const batchPromise = new Promise((resolve, reject) => {
                const store = transaction.objectStore(storeName);
                let firstError = null;

                const fail = (error) => {
                    doneMethod();
                    reject(
                        error ||
                            firstError ||
                            new Error(`IndexedDB ${method} on ${storeName} failed`),
                    );
                };

                transaction.oncomplete = () => {
                    doneMethod();
                    resolve();
                };
                transaction.onabort = () => fail(transaction.error);
                transaction.onerror = () => fail(transaction.error);

                timeoutId = setTimeout(() => {
                    if (!finished) {
                        firstError = new Error("IndexedDB transaction timeout");
                        try {
                            transaction.abort();
                        } catch (e) {
                            logPosMessage(
                                "IndexedDB",
                                method,
                                `Error aborting transaction: ${e.message}`,
                                CONSOLE_COLOR,
                            );
                            fail(firstError);
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

                        request.onerror = (event) => {
                            firstError ??= event.target?.error;
                            logPosMessage(
                                "IndexedDB",
                                method,
                                `Error processing ${method} for ${storeName}: ${event.target?.error}`,
                                CONSOLE_COLOR,
                            );
                            try {
                                transaction.abort();
                            } catch {
                                fail(firstError);
                            }
                        };
                    } catch {
                        logPosMessage(
                            "IndexedDB",
                            method,
                            `Error processing ${method} for ${storeName}: Invalid data format`,
                            CONSOLE_COLOR,
                        );
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
        this.dbVersion = false;

        const delay = Math.min(
            RECONNECT_BASE_DELAY * 2 ** this._reconnectAttempts,
            RECONNECT_MAX_DELAY,
        );
        this._reconnectAttempts++;
        setTimeout(() => this.databaseEventListener(), delay);
    }

    _openFailed(reason) {
        if (!this._isReconnecting) {
            return;
        }
        this._isReconnecting = false;

        if (this._reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            logPosMessage(
                "IndexedDB",
                "_openFailed",
                `Giving up reconnecting to IndexedDB after ${this._reconnectAttempts} attempts (${reason})`,
                CONSOLE_COLOR,
            );
            this._showReloadDialog();
            return;
        }
        this._attemptReconnect();
    }

    _setupVisibilityProbe() {
        if (this._visibilityProbeAttached) {
            return;
        }
        this._visibilityProbeAttached = true;
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
