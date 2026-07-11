// @ts-check

import { describe, expect, onError, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { IndexedDB } from "@web/core/utils/indexed_db";

describe.current.tags("headless");

const CACHE_NAME = "unit_test_disk_cache";

function deleteCacheDB() {
    return new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(CACHE_NAME);
        request.onerror = (error) => console.error(error);
        request.onsuccess = resolve;
    });
}

async function ensureDbIsAbsent() {
    const databases = await window.indexedDB.databases();
    expect(databases.filter((db) => db.name === CACHE_NAME).length).toBe(0, {
        message: "DB is correctly cleaned",
    });
}

test("one cache, read", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    expect(await indexedDB.read("mytable", "test")).toBe(undefined);

    await indexedDB.write("mytable", "test", "value for 'test'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("two caches, read", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    // having 2 caches simulates 2 tabs, each one accessing the same indexeddb
    const indexedDB1 = new IndexedDB(CACHE_NAME, 1);
    await indexedDB1.write("mytable", "test", "value for 'test'");
    expect(await indexedDB1.read("mytable", "test")).toBe("value for 'test'");

    const indexedDB2 = new IndexedDB(CACHE_NAME, 1);
    expect(await indexedDB2.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase(); // deleting twice the same DB don't throw error !
    await ensureDbIsAbsent();
});

test("two caches, read (2)", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    // having 2 caches simulates 2 tabs, each one accessing the same indexeddb
    const indexedDB1 = new IndexedDB(CACHE_NAME, 1);
    const indexedDB2 = new IndexedDB(CACHE_NAME, 1);

    await indexedDB1.write("mytable", "test", "value for 'test'");
    await indexedDB1.write("mytable1", "test", "value for 'test'");

    expect(await indexedDB2.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase(); // deleting twice the same DB don't throw error !
    await ensureDbIsAbsent();
});

test("one cache, invalidate", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    await indexedDB.write("mytable", "test", "value for 'test'");
    await indexedDB.write("mytable", "test2", "value for 'test2'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("mytable", "test2")).toBe("value for 'test2'");

    await indexedDB.invalidate("mytable");
    expect(await indexedDB.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB.read("mytable", "test2")).toBe(undefined);

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("one cache, invalidate multi-tables", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    await indexedDB.write("mytable", "test", "value for 'test'");
    await indexedDB.write("mytable", "test2", "value for 'test2'");
    await indexedDB.write("mytable2", "test", "value for 'test'");
    await indexedDB.write("mytable2", "test2", "value for 'test2'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("mytable", "test2")).toBe("value for 'test2'");
    expect(await indexedDB.read("mytable2", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("mytable2", "test2")).toBe("value for 'test2'");

    await indexedDB.invalidate(["mytable", "mytable2"]);
    expect(await indexedDB.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB.read("mytable", "test2")).toBe(undefined);
    expect(await indexedDB.read("mytable2", "test")).toBe(undefined);
    expect(await indexedDB.read("mytable2", "test2")).toBe(undefined);

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("one cache, invalidate all tables", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    await indexedDB.write("mytable", "test", "value for 'test'");
    await indexedDB.write("mytable2", "test2", "value for 'test2'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("mytable2", "test2")).toBe("value for 'test2'");

    await indexedDB.invalidate();
    expect(await indexedDB.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB.read("mytable2", "test2")).toBe(undefined);

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidate all tables, empty cache", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    //The indexedDB __DBVersion__ is not invalidated
    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    expect(await indexedDB.read("__DBVersion__", "__version__")).toBe(1);
    await indexedDB.invalidate();
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    expect(await indexedDB.read("__DBVersion__", "__version__")).toBe(1);

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidate non existing table", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    await indexedDB.invalidate("nonExistingTable");
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidate non existing and existing table", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    await indexedDB.write("mytable", "test", "value for 'test'");
    await indexedDB.write("mytable", "test2", "value for 'test2'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("mytable", "test2")).toBe("value for 'test2'");

    await indexedDB.invalidate(["nonExistingTable", "mytable"]);
    expect(await indexedDB.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB.read("mytable", "test2")).toBe(undefined);

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("two caches, invalidate", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    // having 2 caches simulates 2 tabs, each one accessing the same indexeddb
    const indexedDB1 = new IndexedDB(CACHE_NAME, 1);
    const indexedDB2 = new IndexedDB(CACHE_NAME, 1);

    await indexedDB1.write("mytable", "test", "value for 'test'");
    await indexedDB1.write("mytable", "test2", "value for 'test2'");
    expect(await indexedDB1.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB1.read("mytable", "test2")).toBe("value for 'test2'");
    expect(await indexedDB2.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB2.read("mytable", "test2")).toBe("value for 'test2'");

    await indexedDB1.invalidate("mytable");
    expect(await indexedDB1.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB1.read("mytable", "test2")).toBe(undefined);
    expect(await indexedDB2.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB2.read("mytable", "test2")).toBe(undefined);

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

test("two caches, new DB version", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB1 = new IndexedDB(CACHE_NAME, 1);
    await indexedDB1.write("mytable", "test", "value for 'test'");
    await indexedDB1.write("mytable", "test2", "value for 'test2'");
    expect(await indexedDB1.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB1.read("mytable", "test2")).toBe("value for 'test2'");

    // simulate a new page, with a new version number for the given databases
    const indexedDB2 = new IndexedDB(CACHE_NAME, 2);
    // DB should not contain tables !
    await indexedDB2.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    await indexedDB2.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    expect(await indexedDB2.read("mytable", "test")).toBe(undefined);
    expect(await indexedDB2.read("mytable", "test2")).toBe(undefined);

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

test("several tables", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);

    await indexedDB.write("table1", "test", "value for 'test'");
    await indexedDB.write("table2", "test2", "value for 'test2'");
    expect(await indexedDB.read("table1", "test")).toBe("value for 'test'");
    expect(await indexedDB.read("table2", "test2")).toBe("value for 'test2'");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("several caches, several tables", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB1 = new IndexedDB(CACHE_NAME, 1);
    await indexedDB1.write("table1", "test", "value for 'test'");
    expect(await indexedDB1.read("table1", "test")).toBe("value for 'test'");

    const indexedDB2 = new IndexedDB(CACHE_NAME, 1);
    await indexedDB2.write("table2", "test", "value for 'test'");
    expect(await indexedDB2.read("table1", "test")).toBe("value for 'test'");
    expect(await indexedDB2.read("table2", "test")).toBe("value for 'test'");

    // check that second table has been correctly setup
    const diskCache3 = new IndexedDB(CACHE_NAME, 1);
    expect(await diskCache3.read("table2", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

// Regression: ``_invalidateWhere`` called ``transaction.commit()`` synchronously
// after opening the cursor, finishing the transaction before ``cursor.continue()``
// could queue the next request (``TransactionInactiveError``). Hit in production
// via ``rpc_cache.invalidateByModel`` on ``ir.filters`` favorites; these tests use
// the real IDB cursor, not a mock.
test("invalidateWhere, deletes only matching keys", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.write("mytable", JSON.stringify({ model: "a" }), "va");
    await indexedDB.write("mytable", JSON.stringify({ model: "b" }), "vb");
    await indexedDB.write("mytable", JSON.stringify({ model: "a", id: 2 }), "va2");

    await indexedDB.invalidateWhere(["mytable"], (key) => {
        try {
            return JSON.parse(key)?.model === "a";
        } catch {
            return false;
        }
    });

    expect(await indexedDB.read("mytable", JSON.stringify({ model: "a" }))).toBe(
        undefined,
    );
    expect(await indexedDB.read("mytable", JSON.stringify({ model: "a", id: 2 }))).toBe(
        undefined,
    );
    expect(await indexedDB.read("mytable", JSON.stringify({ model: "b" }))).toBe("vb");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, iterates across many entries without committing early", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    // Enough entries to guarantee multiple ``cursor.continue()`` ticks; a
    // single tick would not exercise the premature-commit bug.
    const N = 32;
    for (let i = 0; i < N; i += 1) {
        await indexedDB.write("mytable", `key-${i}`, `v${i}`);
    }

    await indexedDB.invalidateWhere(
        ["mytable"],
        (key) => Number(key.slice(4)) % 2 === 0,
    );

    for (let i = 0; i < N; i += 1) {
        const expected = i % 2 === 0 ? undefined : `v${i}`;
        expect(await indexedDB.read("mytable", `key-${i}`)).toBe(expected);
    }

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, spans multiple tables in one transaction", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.write("t1", "a", "1");
    await indexedDB.write("t1", "b", "2");
    await indexedDB.write("t2", "a", "3");
    await indexedDB.write("t2", "b", "4");
    await indexedDB.write("t3", "a", "5"); // not in the targeted set

    await indexedDB.invalidateWhere(["t1", "t2"], (key) => key === "a");

    expect(await indexedDB.read("t1", "a")).toBe(undefined);
    expect(await indexedDB.read("t1", "b")).toBe("2");
    expect(await indexedDB.read("t2", "a")).toBe(undefined);
    expect(await indexedDB.read("t2", "b")).toBe("4");
    expect(await indexedDB.read("t3", "a")).toBe("5");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, predicate that throws keeps the entry", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.write("mytable", "valid", "v1");
    await indexedDB.write("mytable", "boom", "v2");

    await indexedDB.invalidateWhere(["mytable"], (key) => {
        if (key === "boom") {
            throw new Error("predicate failed");
        }
        return true;
    });

    // ``valid`` matched and was deleted; ``boom`` threw and must be kept.
    expect(await indexedDB.read("mytable", "valid")).toBe(undefined);
    expect(await indexedDB.read("mytable", "boom")).toBe("v2");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, no-op when none of the tables exist", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, 1);
    await indexedDB.write("present", "k", "v");

    await indexedDB.invalidateWhere(["missing1", "missing2"], () => true);

    expect(await indexedDB.read("present", "k")).toBe("v");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("blocked database deletion degrades to no-cache instead of hanging", async () => {
    const BLOCKED_DB_NAME = "unit_test_blocked_delete";
    patchWithCleanup(console, {
        warn: (message) => expect.step(`warn:${String(message).slice(0, 24)}`),
    });

    // Seed the DB with a version marker and one entry.
    const seed = new IndexedDB(BLOCKED_DB_NAME, "v1");
    await seed.write("mytable", "k", "v");
    seed._closeCachedDB();

    // A foreign connection (e.g. a frozen tab) that never closes on
    // versionchange: any deleteDatabase request stays blocked behind it.
    /** @type {IDBDatabase} */
    const blocker = await new Promise((resolve, reject) => {
        const request = indexedDB.open(BLOCKED_DB_NAME);
        request.onsuccess = (ev) =>
            resolve(/** @type {IDBOpenDBRequest} */ (ev.target).result);
        request.onerror = () => reject(request.error);
    });

    // A version bump triggers the delete path; reads queue behind it on the
    // instance mutex. Without the onblocked fallback this would hang forever.
    const wrapper = new IndexedDB(BLOCKED_DB_NAME, "v2");
    const readPromise = wrapper.read("mytable", "k");
    // Interleave mock-timer advances with real macrotasks so the (real)
    // IndexedDB blocked event can fire, then the fallback timeout.
    for (let i = 0; i < 10; i++) {
        await advanceTime(500);
    }

    // Degraded: the read resolves (cache miss) instead of hanging, and
    // subsequent operations short-circuit.
    expect(await readPromise).toBe(undefined);
    await wrapper.write("mytable", "k", "ignored");
    expect(await wrapper.read("mytable", "k")).toBe(undefined);
    expect.verifySteps(["warn:IndexedDB delete blocked"]);

    // Cleanup: release the blocker so the pending delete can complete.
    blocker.close();
    await new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(BLOCKED_DB_NAME);
        request.onsuccess = resolve;
        request.onerror = resolve;
    });
});
