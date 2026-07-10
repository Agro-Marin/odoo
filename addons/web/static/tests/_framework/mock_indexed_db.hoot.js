// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

import { afterEach, beforeEach } from "@odoo/hoot";

/**
 * Replace `IndexedDB`'s storage methods with an in-memory mock for the
 * scope in which this is called.  Test files that exercise consumers of
 * `IndexedDB` (e.g. `RPCCache` in `core/network/rpc_cache.test.js`) call
 * this once at module load; the patching is scoped via `beforeEach` /
 * `afterEach` so other test files (notably
 * `core/utils/indexed_db.test.js`, which exercises the real class) are
 * unaffected.
 *
 * Why prototype patching instead of replacing the export?  The Odoo
 * loader stores modules as native ES module namespaces, which the spec
 * freezes; `Object.assign(module, { IndexedDB: Mock })` throws on a
 * frozen namespace.  The class itself is a shared reference: every
 * `import { IndexedDB }` resolves to the same object, and prototype
 * mutations are visible to all instances regardless of import order.
 *
 * Tests assert against `instance.mockIndexedDB.<table>.<key>`, so the
 * patched methods stash their data on that property (lazily on first
 * write).  `_checkVersion` becomes a no-op because the real
 * implementation calls `indexedDB.open` (the browser global) which we
 * explicitly want to bypass.
 *
 * Idempotent across nested `describe` blocks within the same file:
 * the original methods are captured once and re-applied on `afterEach`.
 */
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
            this.mockIndexedDB ??= {};
            if (tables) {
                const tableList = typeof tables === "string" ? [tables] : tables;
                for (const table of tableList) {
                    if (table in this.mockIndexedDB) {
                        this.mockIndexedDB[table] = {};
                    }
                }
            } else {
                this.mockIndexedDB = {};
            }
        };
        // Mirrors production: delete keys per table where predicate returns true.
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
                    } catch {
                        // Predicate error: treat as non-matching.
                    }
                    if (shouldDelete) {
                        delete this.mockIndexedDB[table][key];
                    }
                }
            }
        };
        // Mirrors production: delete entries whose value carries model === <model>;
        // entries without a model property are skipped (not model-scoped).
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
