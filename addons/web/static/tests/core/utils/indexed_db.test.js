// @ts-check

import { describe, expect, onError, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { IDBQuotaExceededError, IndexedDB } from "@web/core/utils/indexed_db";

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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

    expect(await indexedDB.read("mytable", "test")).toBe(undefined);

    await indexedDB.write("mytable", "test", "value for 'test'");
    expect(await indexedDB.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("two caches, read", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB1 = new IndexedDB(CACHE_NAME, "1");
    await indexedDB1.write("mytable", "test", "value for 'test'");
    expect(await indexedDB1.read("mytable", "test")).toBe("value for 'test'");

    const indexedDB2 = new IndexedDB(CACHE_NAME, "1");
    expect(await indexedDB2.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

test("two caches, read (2)", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB1 = new IndexedDB(CACHE_NAME, "1");
    const indexedDB2 = new IndexedDB(CACHE_NAME, "1");

    await indexedDB1.write("mytable", "test", "value for 'test'");
    await indexedDB1.write("mytable1", "test", "value for 'test'");

    expect(await indexedDB2.read("mytable", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

test("one cache, invalidate", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    expect(await indexedDB.read("__DBVersion__", "__version__")).toBe("1");
    await indexedDB.invalidate();
    await indexedDB.execute((db) => {
        expect([...db.objectStoreNames]).toEqual(["__DBVersion__"]);
    });
    expect(await indexedDB.read("__DBVersion__", "__version__")).toBe("1");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidate non existing table", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB1 = new IndexedDB(CACHE_NAME, "1");
    const indexedDB2 = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB1 = new IndexedDB(CACHE_NAME, "1");
    await indexedDB1.write("mytable", "test", "value for 'test'");
    await indexedDB1.write("mytable", "test2", "value for 'test2'");
    expect(await indexedDB1.read("mytable", "test")).toBe("value for 'test'");
    expect(await indexedDB1.read("mytable", "test2")).toBe("value for 'test2'");

    const indexedDB2 = new IndexedDB(CACHE_NAME, "2");
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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");

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

    const indexedDB1 = new IndexedDB(CACHE_NAME, "1");
    await indexedDB1.write("table1", "test", "value for 'test'");
    expect(await indexedDB1.read("table1", "test")).toBe("value for 'test'");

    const indexedDB2 = new IndexedDB(CACHE_NAME, "1");
    await indexedDB2.write("table2", "test", "value for 'test'");
    expect(await indexedDB2.read("table1", "test")).toBe("value for 'test'");
    expect(await indexedDB2.read("table2", "test")).toBe("value for 'test'");

    const diskCache3 = new IndexedDB(CACHE_NAME, "1");
    expect(await diskCache3.read("table2", "test")).toBe("value for 'test'");

    await indexedDB1.deleteDatabase();
    await indexedDB2.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, deletes only matching keys", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
    await indexedDB.write("t1", "a", "1");
    await indexedDB.write("t1", "b", "2");
    await indexedDB.write("t2", "a", "3");
    await indexedDB.write("t2", "b", "4");
    await indexedDB.write("t3", "a", "5");

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

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
    await indexedDB.write("mytable", "valid", "v1");
    await indexedDB.write("mytable", "boom", "v2");

    await indexedDB.invalidateWhere(["mytable"], (key) => {
        if (key === "boom") {
            throw new Error("predicate failed");
        }
        return true;
    });

    expect(await indexedDB.read("mytable", "valid")).toBe(undefined);
    expect(await indexedDB.read("mytable", "boom")).toBe("v2");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("invalidateWhere, no-op when none of the tables exist", async () => {
    onError(() => deleteCacheDB());
    await ensureDbIsAbsent();

    const indexedDB = new IndexedDB(CACHE_NAME, "1");
    await indexedDB.write("present", "k", "v");

    await indexedDB.invalidateWhere(["missing1", "missing2"], () => true);

    expect(await indexedDB.read("present", "k")).toBe("v");

    await indexedDB.deleteDatabase();
    await ensureDbIsAbsent();
});

test("blocked schema-upgrade open degrades to no-cache instead of hanging", async () => {
    const BLOCKED_DB_NAME = "unit_test_blocked_upgrade";
    patchWithCleanup(console, {
        warn: (message) => expect.step(`warn:${String(message).slice(0, 25)}`),
    });

    const seed = new IndexedDB(BLOCKED_DB_NAME, "v1");
    await seed.write("mytable", "k", "v");
    seed._closeCachedDB();

    /** @type {IDBDatabase} */
    const blocker = await new Promise((resolve, reject) => {
        const request = indexedDB.open(BLOCKED_DB_NAME);
        request.onsuccess = (ev) =>
            resolve(/** @type {IDBOpenDBRequest} */ (ev.target).result);
        request.onerror = () => reject(request.error);
    });

    const wrapper = new IndexedDB(BLOCKED_DB_NAME, "v1");
    const readPromise = wrapper.read("newtable", "k");
    for (let i = 0; i < 10; i++) {
        await advanceTime(500);
    }

    expect(await readPromise).toBe(undefined);
    expect(wrapper._degraded).toBe(true);
    await wrapper.write("mytable", "k", "ignored");
    expect(await wrapper.read("mytable", "k")).toBe(undefined);
    expect.verifySteps(["warn:IndexedDB upgrade blocked"]);

    blocker.close();
    await new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(BLOCKED_DB_NAME);
        request.onsuccess = resolve;
        request.onerror = resolve;
    });
});

test("_read rejects when the transaction aborts", async () => {
    const idb = new IndexedDB(CACHE_NAME, "1");
    idb._degraded = true;

    const abortError = new DOMException("Quota exceeded", "QuotaExceededError");
    /** @type {any} */
    const fakeTransaction = {
        error: null,
        objectStore: () => ({ get: () => ({}) }),
    };
    const fakeDb = /** @type {any} */ ({ transaction: () => fakeTransaction });

    const promise = idb._read(fakeDb, "mytable", "k");
    fakeTransaction.error = abortError;
    fakeTransaction.onabort();
    await expect(promise).rejects.toThrow(abortError);
});

test("_invalidate rejects when the transaction aborts", async () => {
    const idb = new IndexedDB(CACHE_NAME, "1");
    idb._degraded = true;

    const abortError = new DOMException("Quota exceeded", "QuotaExceededError");
    /** @type {any} */
    const fakeTransaction = {
        error: null,
        objectStore: () => ({ clear: () => ({}) }),
        commit: () => {},
    };
    const fakeDb = /** @type {any} */ ({
        objectStoreNames: ["mytable"],
        transaction: () => fakeTransaction,
    });

    const promise = idb._invalidate(fakeDb, ["mytable"]);
    fakeTransaction.error = abortError;
    fakeTransaction.onabort();
    await expect(promise).rejects.toThrow(abortError);
});

test("blocked database deletion degrades to no-cache instead of hanging", async () => {
    const BLOCKED_DB_NAME = "unit_test_blocked_delete";
    patchWithCleanup(console, {
        warn: (message) => expect.step(`warn:${String(message).slice(0, 24)}`),
    });

    const seed = new IndexedDB(BLOCKED_DB_NAME, "v1");
    await seed.write("mytable", "k", "v");
    seed._closeCachedDB();

    /** @type {IDBDatabase} */
    const blocker = await new Promise((resolve, reject) => {
        const request = indexedDB.open(BLOCKED_DB_NAME);
        request.onsuccess = (ev) =>
            resolve(/** @type {IDBOpenDBRequest} */ (ev.target).result);
        request.onerror = () => reject(request.error);
    });

    const wrapper = new IndexedDB(BLOCKED_DB_NAME, "v2");
    const readPromise = wrapper.read("mytable", "k");
    for (let i = 0; i < 10; i++) {
        await advanceTime(500);
    }

    expect(await readPromise).toBe(undefined);
    await wrapper.write("mytable", "k", "ignored");
    expect(await wrapper.read("mytable", "k")).toBe(undefined);
    expect.verifySteps(["warn:IndexedDB delete blocked"]);

    blocker.close();
    await new Promise((resolve) => {
        const request = indexedDB.deleteDatabase(BLOCKED_DB_NAME);
        request.onsuccess = resolve;
        request.onerror = resolve;
    });
});

test("a quota failure still surfaces IDBQuotaExceededError when the estimate is partial", async () => {
    patchWithCleanup(console, { error: (message) => expect.step(String(message)) });

    for (const estimate of [{}, { usage: 10 }, null]) {
        patchWithCleanup(navigator.storage, { estimate: async () => estimate });
        const idb = new IndexedDB(CACHE_NAME, "1");
        idb._degraded = true;
        await expect(
            idb._runCallback(/** @type {any} */ ({}), () => {
                throw new DOMException("Quota exceeded", "QuotaExceededError");
            }),
        ).rejects.toThrow(IDBQuotaExceededError);
    }

    expect.verifySteps([
        "IndexedDB error: Quota Exceeded (unknown out of unknown used)",
        "IndexedDB error: Quota Exceeded (10.00B out of unknown used)",
        "IndexedDB error: Quota Exceeded (unknown out of unknown used)",
    ]);
});

test("a quota failure surfaces IDBQuotaExceededError when estimate() itself throws", async () => {
    patchWithCleanup(console, { error: () => {} });
    patchWithCleanup(navigator.storage, {
        estimate: async () => {
            throw new Error("storage unavailable");
        },
    });

    const idb = new IndexedDB(CACHE_NAME, "1");
    idb._degraded = true;
    await expect(
        idb._runCallback(/** @type {any} */ ({}), () => {
            throw new DOMException("Quota exceeded", "QuotaExceededError");
        }),
    ).rejects.toThrow(IDBQuotaExceededError);
});

describe("a callback that rejects must not wedge the mutex", () => {
    test("_deleteDatabase settles when its callback rejects", async () => {
        const idb = new IndexedDB(CACHE_NAME, "v1");
        await expect(
            idb._deleteDatabase(() => Promise.reject(new Error("boom"))),
        ).resolves.toBe(undefined);
        expect.errors(0);
    });

    test("the mutex still runs the work queued behind it", async () => {
        const idb = new IndexedDB(CACHE_NAME, "v1");
        await idb._deleteDatabase(() => Promise.reject(new Error("boom")));
        await idb.write("things", "k", { a: 1 });
        expect(await idb.read("things", "k")).toEqual({ a: 1 });
        await deleteCacheDB();
    });
});
