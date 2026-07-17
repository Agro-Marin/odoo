/** @odoo-module native */
import { Component, useState } from "@odoo/owl";

export class CriticalPOSError extends Component {
    static template = "point_of_sale.CriticalPOSError";
    static props = { error: Object };

    setup() {
        this.state = useState({ expanded: false });
    }
    retry() {
        location.reload();
    }

    // Best-effort dump of every local IndexedDB database to a downloaded JSON
    // file, so a factory reset never silently destroys unsynced (possibly
    // paid) orders. Self-contained on purpose: this screen renders when the
    // app failed to mount, so no POS service can be assumed to exist.
    async exportLocalData() {
        const dump = {};
        const dbs = await indexedDB.databases();
        for (const { name } of dbs) {
            if (!name) {
                continue;
            }
            const db = await new Promise((resolve, reject) => {
                const req = indexedDB.open(name);
                req.onsuccess = () => resolve(req.result);
                req.onerror = () => reject(req.error);
            });
            try {
                dump[name] = {};
                for (const storeName of db.objectStoreNames) {
                    dump[name][storeName] = await new Promise((resolve, reject) => {
                        const req = db
                            .transaction(storeName, "readonly")
                            .objectStore(storeName)
                            .getAll();
                        req.onsuccess = () => resolve(req.result);
                        req.onerror = () => reject(req.error);
                    });
                }
            } finally {
                db.close();
            }
        }
        const blob = new Blob([JSON.stringify(dump)], { type: "application/json" });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `pos-data-backup-${new Date().toISOString().replaceAll(":", "-")}.json`;
        link.click();
        URL.revokeObjectURL(link.href);
    }

    async fullReset() {
        if (
            !window.confirm(
                "This permanently deletes ALL locally cached Point of Sale data on this device, including orders that were not yet synchronized to the server.\n\nA backup file of the local data will be downloaded first.\n\nReset this device?",
            )
        ) {
            return;
        }
        const step = async (fn) => {
            try {
                await fn();
            } catch {
                // keep going
            }
        };

        try {
            // Backup before destroying anything (best effort).
            await step(() => this.exportLocalData());

            // Storage
            await step(() => localStorage.clear());
            await step(() => sessionStorage.clear());

            // Unregister service workers

            if ("serviceWorker" in navigator) {
                await step(async () => {
                    const regs = await navigator.serviceWorker.getRegistrations();
                    await Promise.allSettled(regs.map((r) => r.unregister()));
                });
            }

            // Clear Cache Storage (important for PWAs)
            if ("caches" in window) {
                await step(async () => {
                    const keys = await caches.keys();
                    await Promise.allSettled(keys.map((k) => caches.delete(k)));
                });
            }

            // Delete IndexedDB databases (if supported)
            if ("indexedDB" in window && typeof indexedDB.databases === "function") {
                await step(async () => {
                    const dbs = await indexedDB.databases();
                    const names = dbs.map((db) => db?.name).filter(Boolean);
                    await Promise.allSettled(
                        names.map((name) =>
                            Promise.race([
                                new Promise((resolve, reject) => {
                                    const req = indexedDB.deleteDatabase(name);
                                    req.onsuccess = () => resolve();
                                    req.onerror = () => resolve();
                                    req.onblocked = () => resolve();
                                }),
                                new Promise((resolve) =>
                                    setTimeout(() => {
                                        resolve();
                                    }, 1500),
                                ),
                            ]),
                        ),
                    );
                });
            }
        } finally {
            // Reload
            location.reload();
        }
    }
    async copyToClipboard() {
        const error = this.props.error;
        const text = this.state.expanded ? error.stack : error.message || String(error);
        if (!text) {
            return;
        }

        try {
            await navigator.clipboard.writeText(text);
        } catch (err) {
            console.error("Could not copy text: ", err);
        }
    }
    back() {
        window.history.back();
    }
}
