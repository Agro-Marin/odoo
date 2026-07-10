// @ts-check

import { Deferred, describe, expect, microTick, test, tick } from "@odoo/hoot";
import { mockIndexedDBForTests } from "@web/../tests/_framework/mock_indexed_db.hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { RPCCache } from "@web/core/network/rpc_cache";
import { IDBQuotaExceededError, IndexedDB } from "@web/core/utils/indexed_db";

// rpc_cache asserts against `instance.mockIndexedDB.<table>.<key>` —
// the in-memory store provided by the prototype mock below.  Scoped via
// beforeEach/afterEach so `core/utils/indexed_db.test.js` (which exercises
// the real class) is unaffected.
mockIndexedDBForTests();

const S_PENDING = Symbol("Promise");

/**
 * @param {Promise<any>} promise
 */
function promiseState(promise) {
    return Promise.race([promise, Promise.resolve(S_PENDING)]).then(
        (value) =>
            value === S_PENDING
                ? { status: "pending" }
                : { status: "fulfilled", value },
        (reason) => ({ status: "rejected", reason }),
    );
}

describe.current.tags("headless");

test("RamCache: can cache a simple call", async () => {
    // The fist call to rpcCache.read saves the result on the RamCache.
    // Each next call will retrive the ram cache independently, without executing the fallback
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const rpcCacheRead = (number) =>
        rpcCache.read("table", "key", () => {
            expect.step("fallback");
            return Promise.resolve({ test: number });
        });
    expect(await rpcCacheRead(123)).toEqual({ test: 123 });
    expect(await rpcCacheRead(456)).toEqual({ test: 123 });
    expect(await rpcCacheRead(789)).toEqual({ test: 123 });
    expect.verifySteps(["fallback"]);
});

test("RamCache: ram is set with promises", async () => {
    const def = new Deferred();
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // If two identical calls are made in succession, only one fallback will be made.
    // The second call will get the result of the first call (or a promise if the first call is not yet finish).
    const promFirst = rpcCache.read("table", "key", () => def);
    const promsSecond = rpcCache.read("table", "key", () => def);

    // Only one record in cache
    expect(Object.keys(rpcCache.ramCache.ram.table).length).toBe(1);
    let promInRamCache = rpcCache.ramCache.ram.table.key;

    // Note that proms, promisea and promiseb are the same promise.
    expect(await promiseState(promInRamCache)).toEqual({ status: "pending" });
    expect(await promiseState(promFirst)).toEqual({ status: "pending" });
    expect(await promiseState(promsSecond)).toEqual({ status: "pending" });

    def.resolve({ test: 123 });
    await microTick();

    // The cache is updated when the fetch is back
    promInRamCache = rpcCache.ramCache.ram.table.key;
    expect(await promInRamCache).toEqual({ test: 123 });
    expect(await promFirst).toEqual({ test: 123 });
    expect(await promsSecond).toEqual({ test: 123 });
});

test("PersistentCache: can cache a simple call", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 123,
    });
    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

    // we return the disk cache value.
    expect(
        await rpcCache.read(
            "table",
            "key",
            () => {
                expect.step("Fallback");
                return Promise.resolve(def);
            },
            { type: "disk" },
        ),
    ).toEqual({ test: 123 });
    expect.verifySteps(["Fallback"]);

    // the fallback returned a different value
    def.resolve({ test: 456 });
    await microTick();
    await microTick();
    await microTick();
    // Both caches are updated with the last value
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":456}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 456 },
    });
});

test("invalidate table", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 123,
    });

    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    //invalidate the table
    rpcCache.invalidate("table");

    // `table` is empty
    expect(rpcCache.indexedDB.mockIndexedDB.table).toEqual({});
    expect(rpcCache.ramCache.ram.table).toEqual({});
});

test("invalidate multiple tables", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 123,
    });

    expect(
        await rpcCache.read("table2", "key", () => Promise.resolve({ test: 456 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 456,
    });

    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(rpcCache.indexedDB.mockIndexedDB.table2.key.ciphertext).toBe(
        'encrypted data:{"test":456}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });
    expect(await promiseState(rpcCache.ramCache.ram.table2.key)).toEqual({
        status: "fulfilled",
        value: { test: 456 },
    });

    //invalidate the table
    rpcCache.invalidate(["table", "table2"]);

    // `table` is empty
    expect(rpcCache.indexedDB.mockIndexedDB.table).toEqual({});
    expect(rpcCache.indexedDB.mockIndexedDB.table2).toEqual({});
    expect(rpcCache.ramCache.ram.table).toEqual({});
    expect(rpcCache.ramCache.ram.table2).toEqual({});
});

test("IndexedDB Crypt: can cache a simple call", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.encryptReady;

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 123,
    });
    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

    // we return the disk cache value - decrypted.
    expect(
        await rpcCache.read(
            "table",
            "key",
            () => {
                expect.step("Fallback");
                return Promise.resolve(def);
            },
            { type: "disk" },
        ),
    ).toEqual({ test: 123 });
    expect.verifySteps(["Fallback"]);

    // the fallback returned a different value
    def.resolve({ test: 456 });
});

test("update callback - Ram Value", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 })),
    ).toEqual({
        test: 123,
    });
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    const def = new Deferred();

    // we return the RAM cache value.
    expect(
        await rpcCache.read(
            "table",
            "key",
            () => {
                expect.step("Fallback");
                return Promise.resolve(def);
            },
            {
                update: "always",
                callback: (result) => {
                    expect.step("Callback");
                    expect(result).toEqual({ test: 456 });
                },
            },
        ),
    ).toEqual({ test: 123 });
    expect.verifySteps(["Fallback"]);

    // the fallback returned a different value
    def.resolve({ test: 456 });
    await microTick();
    expect.verifySteps(["Callback"]);
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 456 },
    });
});

test("update callback - reordered keys are not a change (order-independent compare)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // Seed the cache with {a, b}.
    await rpcCache.read("table", "key", () => Promise.resolve({ a: 1, b: 2 }));

    const def = new Deferred();
    let observedHasChanged;
    await rpcCache.read(
        "table",
        "key",
        () => {
            expect.step("Fallback");
            return def;
        },
        {
            update: "always",
            callback: (result, hasChanged) => {
                expect.step("Callback");
                observedHasChanged = hasChanged;
            },
        },
    );
    expect.verifySteps(["Fallback"]);

    // The server returns the SAME values with keys in a different insertion
    // order. A byte-compare (JSON.stringify) would report a spurious change; the
    // deep compare must treat it as unchanged so we don't needlessly re-deliver
    // and re-persist identical payloads on every `update: "always"` refresh.
    def.resolve({ b: 2, a: 1 });
    await microTick();
    expect.verifySteps(["Callback"]);
    expect(observedHasChanged).toBe(false);
});

test("update callback - Disk Value", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
            type: "disk",
        }),
    ).toEqual({
        test: 123,
    });
    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

    // we return the Disk cache value.
    expect(
        await rpcCache.read(
            "table",
            "key",
            () => {
                expect.step("Fallback");
                return Promise.resolve(def);
            },
            {
                type: "disk",
                callback: (result) => {
                    expect.step("Callback");
                    expect(result).toEqual({ test: 456 });
                },
            },
        ),
    ).toEqual({ test: 123 });
    expect.verifySteps(["Fallback"]);

    // the fallback returned a different value
    def.resolve({ test: 456 });
    await microTick();
    await microTick();
    await microTick();
    expect.verifySteps(["Callback"]);
    // Both caches are updated with the last value
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":456}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 456 },
    });
});

test("Ram value shouldn't change (update the rpc response)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // fill the cache
    const res = await rpcCache.read("table", "key", () =>
        Promise.resolve({ test: 123 }),
    );
    expect(res).toEqual({
        test: 123,
    });
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    expect(res).toEqual({ test: 123 });
    res.plop = true;

    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });
});

test("Ram value shouldn't change (update the Ram response)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // fill the cache
    let res = await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }));
    expect(res).toEqual({
        test: 123,
    });
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    const def = new Deferred();
    res = await rpcCache.read("table", "key", () => def);

    // res came from the RAM
    expect(res).toEqual({ test: 123 });
    res.plop = true;

    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });
});

test("Ram value shouldn't change (update the IndexedDB response)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // fill the cache
    let res = await rpcCache.read(
        "table",
        "key",
        () => Promise.resolve({ test: 123 }),
        {
            type: "disk",
        },
    );
    expect(res).toEqual({
        test: 123,
    });
    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    const def = new Deferred();
    res = await rpcCache.read("table", "key", () => def, { type: "disk" });

    // res came from IndexedDB
    expect(res).toEqual({ test: 123 });
    res.plop = true;

    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });
});

test("Changing the result shouldn't force the call to callback with hasChanged (RAM value)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    let res;
    // fill the cache
    res = await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }));
    expect(res).toEqual({
        test: 123,
    });
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // read the RAM Value !
    const def = new Deferred();
    res = await rpcCache.read("table", "key", () => def, {
        callback: (_result, hasChanged) => {
            if (hasChanged) {
                expect.step("callback with hasChanged shouldn't be called");
            }
        },
    });
    expect(res).toEqual({
        test: 123,
    });

    //modify the result
    res.plop = true;
    expect(res).toEqual({
        test: 123,
        plop: true,
    });

    // resolve with the same value as the cache !
    def.resolve({ test: 123 });
});

test("Changing the result shouldn't force the call to callback with hasChanged (IndexedDB value)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    let res;
    // fill the cache
    res = await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
        type: "disk",
    });
    expect(res).toEqual({
        test: 123,
    });
    // Both caches are correctly updated with the fetch values
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    // read the IndexedDB Value !
    const def = new Deferred();
    res = await rpcCache.read("table", "key", () => def, {
        type: "disk",
        update: "always",
        callback: (_res, hasChanged) => {
            if (hasChanged) {
                expect.step("callback with hasChanged shouldn't be called");
            }
        },
    });
    expect(res).toEqual({
        test: 123,
    });

    //modify the result
    res.plop = true;
    expect(res).toEqual({
        test: 123,
        plop: true,
    });

    // resolve with the same value as the cache !
    def.resolve({ test: 123 });
});

test("RamCache (no update): consecutive calls (success)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    const def = new Deferred();
    rpcCache
        .read("table", "key", () => def)
        .then((r) => {
            expect.step(`first prom resolved with ${r}`);
        });
    rpcCache
        .read("table", "key", () => expect.step("should not be called"))
        .then((r) => {
            expect.step(`second prom resolved with ${r}`);
        });

    def.resolve("some value");
    await tick();
    expect.verifySteps([
        "first prom resolved with some value",
        "second prom resolved with some value",
    ]);
});

test("RamCache (no update): consecutive calls and rejected promise", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    const def = new Deferred();
    rpcCache
        .read("table", "key", () => def)
        .catch((e) => {
            expect.step(`first prom rejected ${e.message}`);
        });
    rpcCache
        .read("table", "key", () => expect.step("should not be called"))
        .catch((e) => {
            expect.step(`second prom rejected ${e.message}`);
        });

    def.reject(new Error("boom"));
    await tick();
    expect.verifySteps(["first prom rejected boom", "second prom rejected boom"]);
});

test("RamCache: pending request and call to invalidate", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    const def = new Deferred();
    rpcCache
        .read("table", "key", () => {
            expect.step("fallback first call");
            return def;
        })
        .then((r) => {
            expect.step(`first prom resolved with ${r}`);
        });
    rpcCache.invalidate();
    rpcCache
        .read("table", "key", () => {
            expect.step("fallback second call");
            return Promise.resolve("another value");
        })
        .then((r) => {
            expect.step(`second prom resolved with ${r}`);
        });

    def.resolve("some value");
    await tick();
    expect.verifySteps([
        "fallback first call",
        "fallback second call",
        "second prom resolved with another value",
        "first prom resolved with some value",
    ]);

    // call again to ensure that the correct value is stored in the cache
    rpcCache
        .read("table", "key", () => expect.step("should not be called"))
        .then((r) => {
            expect.step(`third prom resolved with ${r}`);
        });
    await tick();
    expect.verifySteps(["third prom resolved with another value"]);
});

test("RamCache: pending request and call to invalidate, update callbacks", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // populate the cache
    rpcCache.read("table", "key", () => {
        expect.step("first call: fallback");
        return Promise.resolve("initial value");
    });
    await tick();
    expect.verifySteps(["first call: fallback"]);

    // read cache again, with update callback
    const def = new Deferred();
    rpcCache
        .read(
            "table",
            "key",
            () => {
                expect.step("second call: fallback");
                return def;
            },
            {
                callback: (newValue) =>
                    expect.step(`second call: callback ${newValue}`),
                update: "always",
            },
        )
        .then((r) => expect.step(`second call: resolved with ${r}`));
    // read it twice, s.t. there's a pending request
    rpcCache
        .read(
            "table",
            "key",
            () => {
                expect.step("should not be called as there's a pending request");
            },
            {
                callback: (newValue) => expect.step(`third call: callback ${newValue}`),
                update: "always",
            },
        )
        .then((r) => {
            expect.step(`third call: resolved with ${r}`);
        });
    await tick();

    expect.verifySteps([
        "second call: fallback",
        "second call: resolved with initial value",
        "third call: resolved with initial value",
    ]);

    rpcCache.invalidate();
    // sanity check to ensure that cache has been invalidated
    rpcCache.read("table", "key", () => {
        expect.step("fourth call: fallback");
        return Promise.resolve("value after invalidation");
    });
    expect.verifySteps(["fourth call: fallback"]);

    // resolve def => update callbacks of requests 2 and 3 must be called
    def.resolve("updated value");
    await tick();
    expect.verifySteps([
        "second call: callback updated value",
        "third call: callback updated value",
    ]);
});

test("RamCache: pending request and call to invalidate, update callbacks in error", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    const defs = [new Deferred(), new Deferred()];
    rpcCache
        .read("table", "key", () => {
            expect.step("first call: fallback (error)");
            return defs[0]; // will be rejected
        })
        .catch((e) => expect.step(`first call: rejected with ${e}`));

    // invalidate cache and read again
    rpcCache.invalidate();
    rpcCache
        .read("table", "key", () => {
            expect.step("second call: fallback");
            return defs[1];
        })
        .then((r) => expect.step(`second call: resolved with ${r}`));
    await tick();

    expect.verifySteps(["first call: fallback (error)", "second call: fallback"]);

    // reject first def
    defs[0].reject("my_error");
    await tick();
    expect.verifySteps(["first call: rejected with my_error"]);

    // read again, should retrieve same prom as second call which is still pending
    rpcCache
        .read("table", "key", () => expect.step("should not be called"))
        .then((r) => expect.step(`third call: resolved with ${r}`));
    await tick();
    expect.verifySteps([]);

    // read again, should retrieve same prom as second call which is still pending (update "always")
    rpcCache
        .read("table", "key", () => expect.step("should not be called"), {
            update: "always",
        })
        .then((r) => expect.step(`fourth call: resolved with ${r}`));
    await tick();
    expect.verifySteps([]);

    // resolve second def
    defs[1].resolve("updated value");
    await tick();
    expect.verifySteps([
        "second call: resolved with updated value",
        "third call: resolved with updated value",
        "fourth call: resolved with updated value",
    ]);
});

test("DiskCache: multiple consecutive calls, empty cache", async () => {
    // The fist call to rpcCache.read saves the promise to the RAM cache.
    // Each next call (before the end of the first call) retrieves the same result as the first call
    // without executing the fallback.
    // The callback of each call is executed.

    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();
    let id = 0;
    const rpcCacheRead = () => {
        rpcCache.read(
            "table",
            "key",
            () => {
                expect.step("fallback");
                return def;
            },
            {
                callback: () => {
                    expect.step(`callback ${++id}`);
                },
            },
        );
    };

    rpcCacheRead();
    rpcCacheRead();
    rpcCacheRead();

    expect.verifySteps(["fallback"]);
    def.resolve({ test: 123 });
    await tick();

    expect.verifySteps(["callback 1", "callback 2", "callback 3"]);
});

test("DiskCache: multiple consecutive calls, value already in disk cache", async () => {
    // The first call to rpcCache.read saves the promise to the RAM cache.
    // Each next call (before the end of the first call) retrieves the same result as the first call.
    // Each call receives as value the disk value, then each callback is executed.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();

    // fill the cache
    await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
        type: "disk",
    });
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    const rpcCacheRead = (id) =>
        rpcCache.read(
            "table",
            "key",
            () => {
                expect.step(`fallback ${id}`);
                return def;
            },
            {
                type: "disk",
                callback: (result, hasChanged) => {
                    expect.step(
                        `callback ${id}: ${JSON.stringify(result)} ${hasChanged ? "(changed)" : ""}`,
                    );
                },
            },
        );

    rpcCacheRead(1).then((result) =>
        expect.step("res call 1: " + JSON.stringify(result)),
    );
    await tick();
    rpcCacheRead(2).then((result) =>
        expect.step("res call 2: " + JSON.stringify(result)),
    );
    await tick();
    rpcCacheRead(3).then((result) =>
        expect.step("res call 3: " + JSON.stringify(result)),
    );
    await tick();

    expect.verifySteps([
        "fallback 1",
        'res call 1: {"test":123}',
        'res call 2: {"test":123}',
        'res call 3: {"test":123}',
    ]);

    def.resolve({ test: 456 });
    await tick();
    expect.verifySteps([
        'callback 1: {"test":456} (changed)',
        'callback 2: {"test":456} (changed)',
        'callback 3: {"test":456} (changed)',
    ]);
});

test("DiskCache: multiple consecutive calls, fallback fails", async () => {
    // The first call to rpcCache.read saves the promise to the RAM cache.
    // Each next call (before the end of the first call) retrieves the same result as the first call.
    // The fallback fails.
    // Each call receives as value the disk value, callbacks aren't executed.
    // Background refresh failure is logged as warning (not error) since cached data was already served.
    patchWithCleanup(console, { warn: () => {} });
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();

    // fill the cache
    await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
        type: "disk",
    });
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    // simulate a reload (clear ramCache)
    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    const rpcCacheRead = (id) =>
        rpcCache.read(
            "table",
            "key",
            () => {
                expect.step(`fallback ${id}`);
                return def;
            },
            {
                type: "disk",
                callback: () => {
                    expect.step("callback (should not be executed)");
                },
            },
        );

    rpcCacheRead(1).then((result) =>
        expect.step("res call 1: " + JSON.stringify(result)),
    );
    await tick();
    rpcCacheRead(2).then((result) =>
        expect.step("res call 2: " + JSON.stringify(result)),
    );
    await tick();
    rpcCacheRead(3).then((result) =>
        expect.step("res call 3: " + JSON.stringify(result)),
    );
    await tick();

    expect.verifySteps([
        "fallback 1",
        'res call 1: {"test":123}',
        'res call 2: {"test":123}',
        'res call 3: {"test":123}',
    ]);

    def.reject(new Error("my RPCError"));
    await tick();
    await tick();

    expect.verifySteps([]);
    // No error raised — cached data was already served, background failure is
    // silently warned to avoid disrupting the user with an error dialog.
});

test("DiskCache: multiple consecutive calls, empty cache, fallback fails", async () => {
    // The first call to rpcCache.read saves the promise to the RAM cache. That promise will be
    // rejected.
    // Each next call (before the end of the first call) retrieves the same result as the first call.
    // The fallback fails.
    // Each call receives the error.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();

    const rpcCacheRead = (id) =>
        rpcCache.read(
            "table",
            "key",
            () => {
                expect.step(`fallback ${id}`);
                return def;
            },
            {
                type: "disk",
                callback: () => {
                    expect.step("callback (should not be executed)");
                },
            },
        );

    rpcCacheRead(1).catch((error) => expect.step(`error call 1: ${error.message}`));
    await tick();
    rpcCacheRead(2).catch((error) => expect.step(`error call 2: ${error.message}`));
    await tick();
    rpcCacheRead(3).catch((error) => expect.step(`error call 3: ${error.message}`));
    await tick();

    expect.verifySteps(["fallback 1"]);

    def.reject(new Error("my RPCError"));
    await tick();

    expect.verifySteps([
        "error call 1: my RPCError",
        "error call 2: my RPCError",
        "error call 3: my RPCError",
    ]);
});

test("DiskCache: write throws an IDBQuotaExceededError", async () => {
    patchWithCleanup(IndexedDB.prototype, {
        deleteDatabase() {
            expect.step("delete db");
        },
        write() {
            expect.step("write");
            return Promise.reject(new IDBQuotaExceededError());
        },
    });

    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    const fallback = () => {
        expect.step(`fallback`);
        return Promise.resolve("value");
    };
    await rpcCache.read("table", "key", fallback, { type: "disk" });

    await expect.waitForSteps(["fallback", "write", "delete db"]);
});

// ----------------------------------------------------------------------------
// immutable contract
// ----------------------------------------------------------------------------
//
// Three guarantees the cache must keep when ``immutable: true`` is passed:
//   1. The returned value is deep-frozen (mutation throws synchronously).
//   2. Two consecutive immutable reads of the same key return the SAME
//      reference (skip the structuredClone done by the default path).
//   3. A mutable caller (no ``immutable`` flag) on the same key keeps
//      receiving an unfrozen clone — mixing immutable and mutable callers
//      is safe.
//
// Together these unlock the freeze-once-on-write pattern for boot-path reads
// (fields_get, get_views, ir.actions.act_window, currency rates) that are
// known never to be mutated by their consumers but otherwise pay a
// ``structuredClone`` on every cache hit (see the perf rationale in the
// ``shape`` comment in ``rpc_cache.js``).

test("immutable: returned value is deep-frozen", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const fallback = () =>
        Promise.resolve({ id: 1, sub: { name: "alpha", tags: ["a", "b"] } });

    const result = await rpcCache.read("t", "k", fallback, { immutable: true });

    expect(Object.isFrozen(result)).toBe(true);
    expect(Object.isFrozen(result.sub)).toBe(true);
    expect(Object.isFrozen(result.sub.tags)).toBe(true);
});

test("immutable: mutation on returned value throws (strict mode)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const result = await rpcCache.read(
        "t",
        "k",
        () => Promise.resolve({ id: 1, sub: { name: "alpha" } }),
        { immutable: true },
    );

    // ESM modules run in strict mode — frozen property assignment throws.
    expect(() => {
        result.id = 999;
    }).toThrow(TypeError);
    expect(() => {
        result.sub.name = "beta";
    }).toThrow(TypeError);
});

test("immutable: consecutive reads return the same reference", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const fallback = () => Promise.resolve({ id: 1 });

    const a = await rpcCache.read("t", "k", fallback, { immutable: true });
    const b = await rpcCache.read("t", "k", fallback, { immutable: true });
    expect(a).toBe(b);
});

test("immutable: mutable caller after immutable still gets an unfrozen clone", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const fallback = () => Promise.resolve({ id: 1, sub: { name: "alpha" } });

    // First caller opts in to immutable — freezes the cached value.
    const frozen = await rpcCache.read("t", "k", fallback, { immutable: true });
    expect(Object.isFrozen(frozen)).toBe(true);

    // Second caller does NOT pass immutable — must receive a fresh clone.
    const clone = await rpcCache.read("t", "k", fallback);
    expect(clone).not.toBe(frozen);
    expect(Object.isFrozen(clone)).toBe(false);
    expect(Object.isFrozen(clone.sub)).toBe(false);

    // The clone is independently mutable; mutating it must not touch the
    // shared frozen cache entry.
    clone.id = 999;
    clone.sub.name = "beta";
    expect(frozen.id).toBe(1);
    expect(frozen.sub.name).toBe("alpha");
});

// ----------------------------------------------------------------------------
// __version contract (Plan C — server-emitted content hash compare)
// ----------------------------------------------------------------------------
//
// Endpoints that opt in (currently: search_panel_select_range,
// search_panel_select_multi_range) inject a ``__version`` sha256 hash into
// their dict return value.  The cache's ``payloadChanged`` helper uses the
// version compare when present on both sides, falls back to ``jsonEqual``
// otherwise.  These tests pin the three branches.

test("__version: hasChanged=false when both sides carry the same version", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    // First call writes the cached value with __version=v1.
    await rpcCache.read("t", "kv1", () =>
        Promise.resolve({
            values: [{ id: 1 }, { id: 2 }],
            __version: "abc",
        }),
    );
    // Second call (update:always) returns SAME __version even though we
    // intentionally vary an interior field — payload contract is "version
    // is authoritative".
    await rpcCache.read(
        "t",
        "kv1",
        () =>
            Promise.resolve({
                values: [{ id: 1 }, { id: 2 }, { id: 999 }], // would diff via jsonEqual!
                __version: "abc", // …but version says equal
            }),
        {
            update: "always",
            callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
        },
    );
    expect.verifySteps(["changed=false"]);
});

test("__version: hasChanged=true when versions differ", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kv2", () =>
        Promise.resolve({
            values: [{ id: 1 }],
            __version: "old",
        }),
    );
    await rpcCache.read(
        "t",
        "kv2",
        () =>
            Promise.resolve({
                values: [{ id: 1 }],
                __version: "new",
            }),
        {
            update: "always",
            callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
        },
    );
    expect.verifySteps(["changed=true"]);
});

test("__version: fallback to jsonEqual when one side lacks the field", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    // Legacy cached value WITHOUT __version (pre-migration state).
    await rpcCache.read("t", "kv3", () =>
        Promise.resolve({
            values: [{ id: 1 }],
        }),
    );
    // New response carries __version — but old side doesn't, so we fall back
    // to deep-compare.  Contents are identical except for the new __version
    // key, so jsonEqual returns false ⇒ hasChanged=true (the new field counts
    // as a real diff on this transitional call).  Next refresh will be on
    // the version fast path.
    await rpcCache.read(
        "t",
        "kv3",
        () =>
            Promise.resolve({
                values: [{ id: 1 }],
                __version: "v1",
            }),
        {
            update: "always",
            callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
        },
    );
    expect.verifySteps(["changed=true"]);
});

// ----------------------------------------------------------------------------
// Shape fast-path (N1-A)
// ----------------------------------------------------------------------------
//
// Endpoints without ``__version`` (list-returning ``web_read``, template
// dropdowns, m2o special data) fall through to the layered jsonEqual path.
// The shape disqualifier catches the common "row appended / row removed"
// case in O(1), skipping the full deep compare.  These tests pin the
// shape-check branches.

test("shape fast-path: list with different length → changed without jsonEqual", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kshape1", () => Promise.resolve([{ id: 1 }]));
    await rpcCache.read(
        "t",
        "kshape1",
        () =>
            Promise.resolve(
                [{ id: 1 }, { id: 2 }], // length 1 → 2: shape disqualifier fires
            ),
        {
            update: "always",
            callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
        },
    );
    expect.verifySteps(["changed=true"]);
});

test("shape fast-path: same length identical content → falls through to jsonEqual → unchanged", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kshape2", () => Promise.resolve([{ id: 1 }, { id: 2 }]));
    await rpcCache.read("t", "kshape2", () => Promise.resolve([{ id: 1 }, { id: 2 }]), {
        update: "always",
        callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
    });
    expect.verifySteps(["changed=false"]);
});

test("shape fast-path: same length different content → falls through to jsonEqual → changed", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kshape3", () => Promise.resolve([{ id: 1 }, { id: 2 }]));
    await rpcCache.read(
        "t",
        "kshape3",
        () =>
            Promise.resolve(
                [{ id: 1 }, { id: 99 }], // same length, different id: jsonEqual must catch it
            ),
        {
            update: "always",
            callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
        },
    );
    expect.verifySteps(["changed=true"]);
});

test("shape fast-path: array vs object → disqualified without jsonEqual", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kshape4", () => Promise.resolve([{ id: 1 }]));
    // Different top-level shape — extremely defensive but cheap to guarantee.
    await rpcCache.read("t", "kshape4", () => Promise.resolve({ id: 1 }), {
        update: "always",
        callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
    });
    expect.verifySteps(["changed=true"]);
});

// ---------------------------------------------------------------------------
// Model-scoped invalidation (RAM index + IDB value-shape contract)
// ---------------------------------------------------------------------------
//
// The cache maintains a per-table model→keys reverse index in RAM and stores
// the model name plaintext alongside the encrypted IDB value, so
// ``invalidateByModel`` is O(1) on the RAM side and cursor-based with a
// fixed object-property check on the IDB side.  Entries written without a
// ``model`` in their cache settings are not indexed (correct: they are not
// model-scoped) and survive ``invalidateByModel``; the regular
// ``invalidate(table)`` is the only path that touches them.

test("invalidateByModel: only matching-model entries removed from IndexedDB", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    // Seed three disk entries: two res.partner, one res.users — same table.
    // Callers pass ``model`` in cache settings so the entries join the
    // RAM model index and carry ``model`` on the encrypted IDB value.
    const keyPartner1 = JSON.stringify({
        url: "/web/dataset/call_kw/res.partner/web_read",
        params: { model: "res.partner", method: "web_read", args: [[1]] },
    });
    const keyPartner2 = JSON.stringify({
        url: "/web/dataset/call_kw/res.partner/web_read",
        params: { model: "res.partner", method: "web_read", args: [[2]] },
    });
    const keyUser = JSON.stringify({
        url: "/web/dataset/call_kw/res.users/web_read",
        params: { model: "res.users", method: "web_read", args: [[7]] },
    });
    await rpcCache.read("web_read", keyPartner1, () => Promise.resolve({ id: 1 }), {
        type: "disk",
        model: "res.partner",
    });
    await rpcCache.read("web_read", keyPartner2, () => Promise.resolve({ id: 2 }), {
        type: "disk",
        model: "res.partner",
    });
    await rpcCache.read("web_read", keyUser, () => Promise.resolve({ id: 7 }), {
        type: "disk",
        model: "res.users",
    });
    await tick();

    // Sanity: all three present on the mocked disk before invalidation.
    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read).sort()).toEqual(
        [keyPartner1, keyPartner2, keyUser].sort(),
    );

    rpcCache.invalidateByModel(["web_read"], "res.partner");
    await tick();

    // Only res.users entry survives — partner entries were cursor-deleted.
    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read)).toEqual([keyUser]);
});

test("invalidateByModel: entries lacking a model property are skipped", async () => {
    // Pre-migration IDB entries (and any other consumer that writes
    // values without a ``model`` property) must survive
    // ``invalidateByModel`` rather than being treated as matches.
    // The cursor walks every value and checks ``value.model === <model>``;
    // values that are strings, numbers, or objects without a ``model``
    // property simply do not match and stay put.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    // Inject pre-migration / foreign entries directly into the mock —
    // a stringified-then-stored value, a plain object without ``model``,
    // and a malformed key.  All three should survive.
    rpcCache.indexedDB.mockIndexedDB = {
        web_read: {
            "<not-json>": "stale-string",
            "no-model": { ciphertext: new ArrayBuffer(0), iv: new Uint8Array() },
            "wrong-model": {
                ciphertext: new ArrayBuffer(0),
                iv: new Uint8Array(),
                model: "res.users",
            },
        },
    };

    rpcCache.invalidateByModel(["web_read"], "res.partner");
    await tick();

    // None of the three were targeted: two have no model, one has the
    // wrong model.  Pre-fix the JSON.parse predicate would have crashed
    // on the malformed key (try/catch swallowed it) and incorrectly
    // matched the wrong-model entry only if its key parsed to the right
    // model — drift between key and value content was undefined behaviour.
    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read).sort()).toEqual([
        "<not-json>",
        "no-model",
        "wrong-model",
    ]);
});

test("RAM model-index: write+invalidateByModel is O(1) lookup, no JSON.parse", async () => {
    // The reverse index lets ``invalidateByModel`` skip iterating every
    // key in the table.  Pin behaviour by writing entries for several
    // models, invalidating one, and asserting the index is also cleaned.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("web_read", "k1", () => Promise.resolve(1), {
        model: "res.partner",
    });
    await rpcCache.read("web_read", "k2", () => Promise.resolve(2), {
        model: "res.partner",
    });
    await rpcCache.read("web_read", "k3", () => Promise.resolve(3), {
        model: "res.users",
    });

    // Inspect the RAM index directly.
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.partner").size).toBe(2);
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.users").size).toBe(1);

    rpcCache.invalidateByModel(["web_read"], "res.partner");

    // res.partner entries gone from both the cache and the index;
    // res.users untouched.
    expect(rpcCache.ramCache.read("web_read", "k1")).toBe(undefined);
    expect(rpcCache.ramCache.read("web_read", "k2")).toBe(undefined);
    expect(await rpcCache.ramCache.read("web_read", "k3")).toBe(3);
    expect(rpcCache.ramCache.modelIndex.web_read.has("res.partner")).toBe(false);
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.users").size).toBe(1);
});

test("RAM model-index: delete() removes key from the model set", async () => {
    // The cache rarely calls ``delete`` directly (only on rejected
    // requests) but when it does, the index must stay consistent or
    // ``invalidateByModel`` would later try to delete a missing key
    // (harmless) and leak the model→Set entry (memory drift).
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("web_read", "k1", () => Promise.resolve(1), {
        model: "res.partner",
    });
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.partner").size).toBe(1);

    rpcCache.ramCache.delete("web_read", "k1");

    // The empty set is also pruned (we delete the map key when its set
    // hits zero) so ``has(model)`` reports ``false`` instead of a stale
    // empty set sticking around.
    expect(rpcCache.ramCache.modelIndex.web_read.has("res.partner")).toBe(false);
});

test("RAM model-index: invalidate(table) clears the per-table index", async () => {
    // Whole-table invalidation must reset the per-table model index, not
    // just the value map.  Otherwise a subsequent write to the same
    // table would find a stale model→Set entry from before the clear.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("web_read", "k1", () => Promise.resolve(1), {
        model: "res.partner",
    });
    await rpcCache.read("web_read_group", "k2", () => Promise.resolve(2), {
        model: "res.partner",
    });

    rpcCache.invalidate(["web_read"]);

    expect(rpcCache.ramCache.modelIndex.web_read.size).toBe(0);
    // Other tables untouched.
    expect(rpcCache.ramCache.modelIndex.web_read_group.get("res.partner").size).toBe(1);
});

test("RAM model-index: overwriting same key with a different model rebalances the index", async () => {
    // Rare but legitimate: two callers hit the same URL+params (so same
    // cache key) but the second supplies a different model name.  The
    // first model's Set must drop the key; the second must gain it,
    // otherwise ``invalidateByModel(firstModel)`` would later wrongly
    // delete the second caller's entry.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    rpcCache.ramCache.write("web_read", "k", Promise.resolve(1), "res.partner");
    rpcCache.ramCache.write("web_read", "k", Promise.resolve(2), "res.users");

    expect(rpcCache.ramCache.modelIndex.web_read.has("res.partner")).toBe(false);
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.users").has("k")).toBe(true);

    rpcCache.invalidateByModel(["web_read"], "res.partner");

    // Entry survives — it now belongs to res.users.
    expect(await rpcCache.ramCache.read("web_read", "k")).toBe(2);
});

// ---------------------------------------------------------------------------
// onFulfilled robustness: throwing subscriber callbacks
// ---------------------------------------------------------------------------
//
// A subscriber callback that throws must not abort ``onFulfilled`` before the
// cache bookkeeping (pendingRequests cleanup, RAM write, disk-write
// scheduling).  Pre-fix, one throwing callback left a dead entry in
// ``pendingRequests``: every future read joined it forever, all
// ``update: "always"`` refreshes for that key died, and the throw escaped as
// an unhandled rejection.

test("throwing subscriber callback does not wedge the key nor starve other callbacks", async () => {
    patchWithCleanup(console, {
        error: () => expect.step("console.error"),
    });
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    // Seed the caches.
    await rpcCache.read("table", "key", () => Promise.resolve({ test: 1 }), {
        type: "disk",
    });
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":1}',
    );

    // Refresh with two subscribers on the same pending request: the first
    // throws, the second must still be notified.
    const def = new Deferred();
    rpcCache.read(
        "table",
        "key",
        () => {
            expect.step("refresh fallback");
            return def;
        },
        {
            type: "disk",
            update: "always",
            callback: () => {
                expect.step("callback 1 (throws)");
                throw new Error("subscriber boom");
            },
        },
    );
    rpcCache.read(
        "table",
        "key",
        () => expect.step("should not be called (pending request)"),
        {
            type: "disk",
            update: "always",
            callback: (value) => expect.step(`callback 2: ${value.test}`),
        },
    );
    expect.verifySteps(["refresh fallback"]);

    def.resolve({ test: 2 });
    await tick();
    expect.verifySteps(["callback 1 (throws)", "console.error", "callback 2: 2"]);

    // Bookkeeping ran despite the throw: no dead pending request, RAM and
    // disk both hold the fresh value.
    expect(Object.keys(rpcCache.pendingRequests)).toEqual([]);
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 2 },
    });
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":2}',
    );

    // Later reads/refreshes of the same key still work: the fallback fires
    // again and its callback is delivered.
    const def2 = new Deferred();
    rpcCache
        .read(
            "table",
            "key",
            () => {
                expect.step("second refresh fallback");
                return def2;
            },
            {
                type: "disk",
                update: "always",
                callback: (value) => expect.step(`callback 3: ${value.test}`),
            },
        )
        .then((r) => expect.step(`read resolved with ${r.test}`));
    await tick();
    expect.verifySteps(["second refresh fallback", "read resolved with 2"]);

    def2.resolve({ test: 3 });
    await tick();
    expect.verifySteps(["callback 3: 3"]);
});

// ---------------------------------------------------------------------------
// Disk-cache stale-persist race (invalidation generations)
// ---------------------------------------------------------------------------
//
// ``onFulfilled`` removes the request from ``pendingRequests`` and then runs
// the async encrypt→IDB-write chain.  An invalidation landing in that window
// can no longer flag the request; pre-fix its IDB clear was queued first and
// the write landed after it, durably persisting pre-invalidation data (served
// as truth on the next reload for ``update: "once"`` consumers such as
// get_views).  The per-table generation counter must drop such writes.

/**
 * Gate ``rpcCache.crypto.encrypt`` on a deferred so a test can act inside
 * the RPC-resolution → disk-write window.
 *
 * @param {RPCCache} rpcCache
 * @returns {Deferred} resolve it to let pending encryptions proceed
 */
function gateEncrypt(rpcCache) {
    const gate = new Deferred();
    const crypto = rpcCache.crypto;
    const originalEncrypt = crypto.encrypt.bind(crypto);
    crypto.encrypt = async (value) => {
        await gate;
        return originalEncrypt(value);
    };
    return gate;
}

test("invalidate between RPC resolution and disk write persists NO stale entry", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const gate = gateEncrypt(rpcCache);

    const def = new Deferred();
    rpcCache.read("table", "key", () => def, { type: "disk" });
    def.resolve({ test: 123 });
    await tick();

    // The RPC resolved: the request already left ``pendingRequests`` (so
    // ``invalidate`` cannot flag it) while the encrypt is still gated.
    expect(Object.keys(rpcCache.pendingRequests)).toEqual([]);

    // Invalidation arrives inside the window.
    rpcCache.invalidate("table");
    await tick();

    // Release the encryption: the queued write must be skipped as stale.
    gate.resolve();
    await tick();
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB?.table?.key).toBe(undefined);
    // RAM stays empty too — nothing resurrects the invalidated value.
    expect(rpcCache.ramCache.read("table", "key")).toBe(undefined);
});

test("invalidateByModel between RPC resolution and disk write persists NO stale entry", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const gate = gateEncrypt(rpcCache);

    const def = new Deferred();
    rpcCache.read("web_read", "key", () => def, {
        type: "disk",
        model: "res.partner",
    });
    def.resolve({ id: 1 });
    await tick();
    expect(Object.keys(rpcCache.pendingRequests)).toEqual([]);

    rpcCache.invalidateByModel(["web_read"], "res.partner");
    await tick();

    gate.resolve();
    await tick();
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB?.web_read?.key).toBe(undefined);
});

test("invalidating an unrelated table does not drop a concurrent disk write", async () => {
    // Pins the per-table generation design: only invalidations touching the
    // write's own table may skip the persist.
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const gate = gateEncrypt(rpcCache);

    const def = new Deferred();
    rpcCache.read("table", "key", () => def, { type: "disk" });
    def.resolve({ test: 123 });
    await tick();

    // Unrelated-table invalidation inside the window: must NOT affect the
    // pending write for "table".
    rpcCache.invalidate("other_table");
    await tick();

    gate.resolve();
    await tick();
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
});
