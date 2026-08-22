// @ts-check

import { afterEach, beforeEach } from "@odoo/hoot";

export function mockIndexedDBForTests() {
    /** @type {Record<string, any> | null} */
    let originalMethods = null;

    beforeEach(() => {
        const indexedDbModule = odoo.loader.modules.get("@web/core/utils/indexed_db");
        if (!indexedDbModule?.IndexedDB) {
            return;
        }
        const proto = indexedDbModule.IndexedDB.prototype;
        originalMethods = {
            write: proto.write,
            read: proto.read,
            invalidate: proto.invalidate,
            invalidateWhere: proto.invalidateWhere,
            invalidateByModel: proto.invalidateByModel,
            deleteDatabase: proto.deleteDatabase,
            _checkVersion: proto._checkVersion,
        };

        proto.write = async function (table, key, value) {
            this.mockIndexedDB ??= {};
            this.mockIndexedDB[table] ??= {};
            this.mockIndexedDB[table][key] = value;
        };
        proto.read = async function (table, key) {
            return this.mockIndexedDB?.[table]?.[key];
        };
        proto.invalidate = async function (tables = null) {
            /** @type {Record<string, any>} */
            const store = (this.mockIndexedDB ??= {});
            if (tables) {
                const tableList = typeof tables === "string" ? [tables] : tables;
                for (const table of tableList) {
                    if (table in store) {
                        store[table] = {};
                    }
                }
            } else {
                this.mockIndexedDB = {};
            }
        };
        proto.invalidateWhere = async function (tables, predicate) {
            this.mockIndexedDB ??= {};
            const tableList = typeof tables === "string" ? [tables] : tables;
            for (const table of tableList || []) {
                if (!(table in this.mockIndexedDB)) {
                    continue;
                }
                for (const key of Object.keys(this.mockIndexedDB[table])) {
                    let shouldDelete = false;
                    try {
                        shouldDelete = predicate(key);
                    } catch {}
                    if (shouldDelete) {
                        delete this.mockIndexedDB[table][key];
                    }
                }
            }
        };
        proto.invalidateByModel = async function (tables, model) {
            this.mockIndexedDB ??= {};
            const tableList = typeof tables === "string" ? [tables] : tables;
            for (const table of tableList || []) {
                if (!(table in this.mockIndexedDB)) {
                    continue;
                }
                for (const key of Object.keys(this.mockIndexedDB[table])) {
                    const value = this.mockIndexedDB[table][key];
                    if (value && typeof value === "object" && value.model === model) {
                        delete this.mockIndexedDB[table][key];
                    }
                }
            }
        };
        proto.deleteDatabase = async function () {
            this.mockIndexedDB = {};
        };
        proto._checkVersion = async function () {};
    });

    afterEach(() => {
        if (!originalMethods) {
            return;
        }
        const indexedDbModule = odoo.loader.modules.get("@web/core/utils/indexed_db");
        if (indexedDbModule?.IndexedDB) {
            Object.assign(indexedDbModule.IndexedDB.prototype, originalMethods);
        }
        originalMethods = null;
    });
}
