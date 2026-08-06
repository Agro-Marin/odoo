// @ts-check

import { after, Deferred, describe, expect, microTick, test, tick } from "@odoo/hoot";
import { mockFetch } from "@odoo/hoot-mock";
import { mockIndexedDBForTests } from "@web/../tests/_framework/mock_indexed_db.hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import {
    ConnectionAbortedError,
    ConnectionLostError,
    InvalidResponseError,
    rpc,
    rpcBus,
} from "@web/core/network/rpc";
import { RAM_CACHE_MAX_ENTRIES, RPCCache } from "@web/core/network/rpc_cache";
import { buildKey } from "@web/core/network/rpc_dedup";
import { IDBQuotaExceededError, IndexedDB } from "@web/core/utils/indexed_db";

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

    const promFirst = rpcCache.read("table", "key", () => def);
    const promsSecond = rpcCache.read("table", "key", () => def);

    expect(Object.keys(rpcCache.ramCache.ram.table).length).toBe(1);
    let promInRamCache = rpcCache.ramCache.ram.table.key;

    expect(await promiseState(promInRamCache)).toEqual({ status: "pending" });
    expect(await promiseState(promFirst)).toEqual({ status: "pending" });
    expect(await promiseState(promsSecond)).toEqual({ status: "pending" });

    def.resolve({ test: 123 });
    await microTick();

    promInRamCache = rpcCache.ramCache.ram.table.key;
    expect(await promInRamCache).toEqual({ test: 123 });
    expect(await promFirst).toEqual({ test: 123 });
    expect(await promsSecond).toEqual({ test: 123 });
});

test("abortPending: a silently-aborted cache miss can be re-fetched fresh", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    let fallbackCalls = 0;
    const hung = new Deferred();
    rpcCache.read("table", "key", () => {
        fallbackCalls++;
        return hung;
    });
    expect(fallbackCalls).toBe(1);
    expect("table/key" in rpcCache.pendingRequests).toBe(true);

    rpcCache.abortPending("table", "key");
    expect("table/key" in rpcCache.pendingRequests).toBe(false);

    const fresh = rpcCache.read("table", "key", () => {
        fallbackCalls++;
        return Promise.resolve({ test: 7 });
    });
    expect(fallbackCalls).toBe(2);
    expect(await fresh).toEqual({ test: 7 });
});

test("abortPending: identity guard — a stale abort does not evict a newer request", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    let requestA;
    const hungA = new Deferred();
    rpcCache.read("table", "key", (request) => {
        requestA = request;
        return hungA;
    });
    expect("table/key" in rpcCache.pendingRequests).toBe(true);

    rpcCache.invalidate("table");
    expect("table/key" in rpcCache.pendingRequests).toBe(false);
    const hungB = new Deferred();
    rpcCache.read("table", "key", () => hungB);
    const requestB = rpcCache.pendingRequests["table/key"];
    expect(requestB).not.toBe(requestA);

    rpcCache.abortPending("table", "key", requestA);
    expect("table/key" in rpcCache.pendingRequests).toBe(true);
    expect(rpcCache.pendingRequests["table/key"]).toBe(requestB);

    rpcCache.abortPending("table", "key", requestB);
    expect("table/key" in rpcCache.pendingRequests).toBe(false);
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
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

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

    def.resolve({ test: 456 });
    await microTick();
    await microTick();
    await microTick();
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

    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.invalidate("table");

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

    rpcCache.invalidate(["table", "table2"]);

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
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

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
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});
    const def = new Deferred();

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

    def.resolve({ test: 456 });
    await microTick();
    await microTick();
    await microTick();
    expect.verifySteps(["Callback"]);
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
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    const def = new Deferred();
    res = await rpcCache.read("table", "key", () => def, { type: "disk" });

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
    res = await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }));
    expect(res).toEqual({
        test: 123,
    });
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

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

    res.plop = true;
    expect(res).toEqual({
        test: 123,
        plop: true,
    });

    def.resolve({ test: 123 });
});

test("Changing the result shouldn't force the call to callback with hasChanged (IndexedDB value)", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    let res;
    res = await rpcCache.read("table", "key", () => Promise.resolve({ test: 123 }), {
        type: "disk",
    });
    expect(res).toEqual({
        test: 123,
    });
    await microTick();
    await microTick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        `encrypted data:{"test":123}`,
    );
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 123 },
    });

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

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

    res.plop = true;
    expect(res).toEqual({
        test: 123,
        plop: true,
    });

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

    rpcCache.read("table", "key", () => {
        expect.step("first call: fallback");
        return Promise.resolve("initial value");
    });
    await tick();
    expect.verifySteps(["first call: fallback"]);

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
    rpcCache.read("table", "key", () => {
        expect.step("fourth call: fallback");
        return Promise.resolve("value after invalidation");
    });
    expect.verifySteps(["fourth call: fallback"]);

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
            return defs[0];
        })
        .catch((e) => expect.step(`first call: rejected with ${e}`));

    rpcCache.invalidate();
    rpcCache
        .read("table", "key", () => {
            expect.step("second call: fallback");
            return defs[1];
        })
        .then((r) => expect.step(`second call: resolved with ${r}`));
    await tick();

    expect.verifySteps(["first call: fallback (error)", "second call: fallback"]);

    defs[0].reject("my_error");
    await tick();
    expect.verifySteps(["first call: rejected with my_error"]);

    rpcCache
        .read("table", "key", () => expect.step("should not be called"))
        .then((r) => expect.step(`third call: resolved with ${r}`));
    await tick();
    expect.verifySteps([]);

    rpcCache
        .read("table", "key", () => expect.step("should not be called"), {
            update: "always",
        })
        .then((r) => expect.step(`fourth call: resolved with ${r}`));
    await tick();
    expect.verifySteps([]);

    defs[1].resolve("updated value");
    await tick();
    expect.verifySteps([
        "second call: resolved with updated value",
        "third call: resolved with updated value",
        "fourth call: resolved with updated value",
    ]);
});

test("DiskCache: multiple consecutive calls, empty cache", async () => {
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
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();

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
    patchWithCleanup(console, { warn: () => {} });
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();

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
});

test("update:always: an aborted refresh is not reported as a failure", async () => {
    const rpcCache = new RPCCache("mockRpc", 1, null);
    await rpcCache.read("table", "key", () => Promise.resolve({ v: 1 }), {
        type: "ram",
    });

    /** @type {string[]} */
    const warnings = [];
    patchWithCleanup(console, {
        warn: (/** @type {any[]} */ ...args) => warnings.push(String(args[0])),
    });
    const failures = [];
    const onFail = (/** @type {any} */ ev) => failures.push(ev.detail.error);
    rpcBus.addEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);

    const def = new Deferred();
    // `rpc`'s abort() rejects the inner request with exactly this.
    const res = await rpcCache.read("table", "key", () => def, {
        type: "ram",
        update: "always",
    });
    expect(res).toEqual({ v: 1 });

    def.reject(new ConnectionAbortedError("fetch abort"));
    await tick();
    await tick();

    // The caller asked for the refresh to stop; that is not a failure to
    // report, on the console or on the bus.
    expect(
        warnings.filter((w) => w.includes("background refresh failed")),
    ).toHaveLength(0);
    expect(failures).toHaveLength(0);
    rpcBus.removeEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);
});

test("silent update:always: ConnectionLostError refresh does not float a rejection", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("table", "key", () => Promise.resolve({ v: 1 }), {
        type: "ram",
    });

    const failures = [];
    const onFail = (/** @type {any} */ ev) => failures.push(ev.detail.error);
    rpcBus.addEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);

    const def = new Deferred();
    const res = await rpcCache.read("table", "key", () => def, {
        type: "ram",
        update: "always",
        silent: true,
    });
    expect(res).toEqual({ v: 1 });

    def.reject(new ConnectionLostError("/web/dataset/call_kw"));
    await tick();
    await tick();

    expect(failures.length).toBe(1);
    expect(failures[0]).toBeInstanceOf(ConnectionLostError);
    rpcBus.removeEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);
});

test("update:always: an InvalidResponseError refresh warns but does not signal offline", async () => {
    // `InvalidResponseError` extends `ConnectionLostError` but is not
    // connectivity loss (e.g. a session-expired refresh got a login page, not
    // JSON), so it must NOT fire the offline `BACKGROUND_REFRESH_FAILED` signal
    // -- only a genuine `ConnectionLostError` does. It falls to a plain warning.
    const rpcCache = new RPCCache("mockRpc", 1, null);
    await rpcCache.read("table", "key", () => Promise.resolve({ v: 1 }), {
        type: "ram",
    });

    /** @type {string[]} */
    const warnings = [];
    patchWithCleanup(console, {
        warn: (/** @type {any[]} */ ...args) => warnings.push(String(args[0])),
    });
    const failures = [];
    const onFail = (/** @type {any} */ ev) => failures.push(ev.detail.error);
    rpcBus.addEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);

    const def = new Deferred();
    const res = await rpcCache.read("table", "key", () => def, {
        type: "ram",
        update: "always",
    });
    expect(res).toEqual({ v: 1 });

    def.reject(new InvalidResponseError("/web/dataset/call_kw", 200));
    await tick();
    await tick();

    expect(failures).toHaveLength(0); // not signalled as offline
    expect(
        warnings.filter((w) => w.includes("background refresh failed")),
    ).toHaveLength(1);
    rpcBus.removeEventListener(RpcEvent.BACKGROUND_REFRESH_FAILED, onFail);
});

test("DiskCache: multiple consecutive calls, empty cache, fallback fails", async () => {
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

    const frozen = await rpcCache.read("t", "k", fallback, { immutable: true });
    expect(Object.isFrozen(frozen)).toBe(true);

    const clone = await rpcCache.read("t", "k", fallback);
    expect(clone).not.toBe(frozen);
    expect(Object.isFrozen(clone)).toBe(false);
    expect(Object.isFrozen(clone.sub)).toBe(false);

    clone.id = 999;
    clone.sub.name = "beta";
    expect(frozen.id).toBe(1);
    expect(frozen.sub.name).toBe("alpha");
});

test("__version: hasChanged=false when both sides carry the same version", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kv1", () =>
        Promise.resolve({
            values: [{ id: 1 }, { id: 2 }],
            __version: "abc",
        }),
    );
    await rpcCache.read(
        "t",
        "kv1",
        () =>
            Promise.resolve({
                values: [{ id: 1 }, { id: 2 }, { id: 999 }],
                __version: "abc",
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
    await rpcCache.read("t", "kv3", () =>
        Promise.resolve({
            values: [{ id: 1 }],
        }),
    );
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

test("__version: a disk round-trip of an ARRAY payload preserves the version", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read(
        "t",
        "karr",
        () =>
            Promise.resolve(
                Object.assign([{ id: 1 }, { id: 2 }], { __version: "abc" }),
            ),
        { type: "disk" },
    );
    await tick();

    const stored = rpcCache.indexedDB.mockIndexedDB.t.karr;
    expect(stored.ciphertext).toBe('encrypted data:[{"id":1},{"id":2}]');
    expect(stored.version).toBe("abc");

    rpcCache.ramCache.invalidate();
    expect(rpcCache.ramCache.ram).toEqual({});

    const def = new Deferred();
    await rpcCache.read("t", "karr", () => def, {
        type: "disk",
        update: "always",
        callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
    });
    def.resolve(
        Object.assign([{ id: 1 }, { id: 2 }, { id: 999 }], { __version: "abc" }),
    );
    await tick();
    expect.verifySteps(["changed=false"]);
});

test("shape fast-path: list with different length → changed without jsonEqual", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    await rpcCache.read("t", "kshape1", () => Promise.resolve([{ id: 1 }]));
    await rpcCache.read("t", "kshape1", () => Promise.resolve([{ id: 1 }, { id: 2 }]), {
        update: "always",
        callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
    });
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
        () => Promise.resolve([{ id: 1 }, { id: 99 }]),
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
    await rpcCache.read("t", "kshape4", () => Promise.resolve({ id: 1 }), {
        update: "always",
        callback: (_value, hasChanged) => expect.step(`changed=${hasChanged}`),
    });
    expect.verifySteps(["changed=true"]);
});

test("invalidateByModel: only matching-model entries removed from IndexedDB", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
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

    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read).sort()).toEqual(
        [keyPartner1, keyPartner2, keyUser].sort(),
    );

    rpcCache.invalidateByModel(["web_read"], "res.partner");
    await tick();

    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read)).toEqual([keyUser]);
});

test("invalidateByModel: entries lacking a model property are skipped", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
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

    expect(Object.keys(rpcCache.indexedDB.mockIndexedDB.web_read).sort()).toEqual([
        "<not-json>",
        "no-model",
        "wrong-model",
    ]);
});

test("RAM model-index: write+invalidateByModel is O(1) lookup, no JSON.parse", async () => {
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

    expect(rpcCache.ramCache.modelIndex.web_read.get("res.partner").size).toBe(2);
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.users").size).toBe(1);

    rpcCache.invalidateByModel(["web_read"], "res.partner");

    expect(rpcCache.ramCache.read("web_read", "k1")).toBe(undefined);
    expect(rpcCache.ramCache.read("web_read", "k2")).toBe(undefined);
    expect(await rpcCache.ramCache.read("web_read", "k3")).toBe(3);
    expect(rpcCache.ramCache.modelIndex.web_read.has("res.partner")).toBe(false);
    expect(rpcCache.ramCache.modelIndex.web_read.get("res.users").size).toBe(1);
});

test("RAM model-index: delete() removes key from the model set", async () => {
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

    expect(rpcCache.ramCache.modelIndex.web_read.has("res.partner")).toBe(false);
});

test("RAM model-index: invalidate(table) clears the per-table index", async () => {
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
    expect(rpcCache.ramCache.modelIndex.web_read_group.get("res.partner").size).toBe(1);
});

test("RAM model-index: overwriting same key with a different model rebalances the index", async () => {
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

    expect(await rpcCache.ramCache.read("web_read", "k")).toBe(2);
});

test("throwing subscriber callback does not wedge the key nor starve other callbacks", async () => {
    patchWithCleanup(console, {
        error: () => expect.step("console.error"),
    });
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );

    await rpcCache.read("table", "key", () => Promise.resolve({ test: 1 }), {
        type: "disk",
    });
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":1}',
    );

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

    expect(Object.keys(rpcCache.pendingRequests)).toEqual([]);
    expect(await promiseState(rpcCache.ramCache.ram.table.key)).toEqual({
        status: "fulfilled",
        value: { test: 2 },
    });
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":2}',
    );

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

    expect(Object.keys(rpcCache.pendingRequests)).toEqual([]);

    rpcCache.invalidate("table");
    await tick();

    gate.resolve();
    await tick();
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB?.table?.key).toBe(undefined);
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

    rpcCache.invalidate("other_table");
    await tick();

    gate.resolve();
    await tick();
    await tick();
    expect(rpcCache.indexedDB.mockIndexedDB.table.key.ciphertext).toBe(
        'encrypted data:{"test":123}',
    );
});

test("joined subscribers receive callbacks through their OWN shape", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    const def = new Deferred();
    const p1 = rpcCache.read("table", "key", () => def, {
        update: "always",
        immutable: true,
        callback: (result) => {
            expect.step("cb-immutable");
            expect(Object.isFrozen(result)).toBe(true);
        },
    });
    const p2 = rpcCache.read("table", "key", () => def, {
        update: "always",
        immutable: false,
        callback: (result) => {
            expect.step("cb-mutable");
            expect(Object.isFrozen(result)).toBe(false);
            result.mutated = true;
        },
    });

    def.resolve({ test: 1 });
    await tick();
    expect.verifySteps(["cb-immutable", "cb-mutable"]);
    expect(Object.isFrozen(await p1)).toBe(true);
    expect(Object.isFrozen(await p2)).toBe(false);
});

test("checkSize: prefers the IndexedDB-specific usage over the origin-wide figure", async () => {
    const TWO_GB = 2 * 1024 * 1024 * 1024;
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    /** @type {any} */
    let estimateResult;
    patchWithCleanup(navigator.storage, {
        estimate: async () => estimateResult,
    });
    /** @type {any} */ (rpcCache).indexedDB = {
        deleteDatabase: () => expect.step("deleteDatabase"),
    };
    const warnings = [];
    patchWithCleanup(console, {
        warn: (...args) => warnings.push(args),
    });

    estimateResult = {
        usage: TWO_GB + 1,
        usageDetails: { indexedDB: 1024 },
    };
    await rpcCache.checkSize();
    expect.verifySteps([]);

    estimateResult = {
        usage: TWO_GB + 1,
        usageDetails: { indexedDB: TWO_GB + 1 },
    };
    await rpcCache.checkSize();
    expect.verifySteps(["deleteDatabase"]);

    warnings.length = 0;
    estimateResult = { usage: TWO_GB + 1 };
    await rpcCache.checkSize();
    expect.verifySteps([]);
    expect(warnings.length).toBe(1);
});

test("purgeStorage deletes the on-disk database", async () => {
    const rpcCache = new RPCCache(
        "mockRpc",
        1,
        "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b",
    );
    /** @type {any} */ (rpcCache).indexedDB = {
        deleteDatabase: () => expect.step("deleteDatabase"),
    };

    await rpcCache.purgeStorage();

    expect.verifySteps(["deleteDatabase"]);
});

test("purgeStorage is a no-op (and does not throw) without a disk cache", async () => {
    const rpcCache = new RPCCache("mockRpc", 1); // no secret -> disk cache disabled
    expect(rpcCache.indexedDB).toBe(null);

    await rpcCache.purgeStorage();

    expect.verifySteps([]);
});

const RAM_SECRET = "85472d41873cdb504b7c7dfecdb8993d90db142c4c03e6d94c4ae37a7771dc5b";

test("RamCache: bounded by RAM_CACHE_MAX_ENTRIES (LRU eviction)", () => {
    const rc = new RPCCache("mockRpc", 1, RAM_SECRET).ramCache;
    for (let i = 0; i < RAM_CACHE_MAX_ENTRIES + 5; i++) {
        rc.write("t", `k${i}`, Promise.resolve(i));
    }
    expect(rc.lru.size).toBe(RAM_CACHE_MAX_ENTRIES);
    expect(Object.keys(rc.ram.t).length).toBe(RAM_CACHE_MAX_ENTRIES);
    expect(rc.read("t", "k0")).toBe(undefined);
    expect(rc.read("t", "k4")).toBe(undefined);
    expect(rc.read("t", "k5")).not.toBe(undefined);
    expect(rc.read("t", `k${RAM_CACHE_MAX_ENTRIES + 4}`)).not.toBe(undefined);
});

test("RamCache: a read keeps its entry warm across later eviction", () => {
    const rc = new RPCCache("mockRpc", 1, RAM_SECRET).ramCache;
    for (let i = 0; i < RAM_CACHE_MAX_ENTRIES; i++) {
        rc.write("t", `k${i}`, Promise.resolve(i));
    }
    expect(rc.read("t", "k0")).not.toBe(undefined);
    rc.write("t", "new1", Promise.resolve("a"));
    rc.write("t", "new2", Promise.resolve("b"));
    expect(rc.read("t", "k0")).not.toBe(undefined);
    expect(rc.read("t", "k1")).toBe(undefined);
    expect(rc.read("t", "k2")).toBe(undefined);
});

test("no disk secret: RAM caching still works, disk layer disabled", async () => {
    const rpcCache = new RPCCache("mockRpc", 1, null);
    expect(rpcCache.diskEnabled).toBe(false);
    expect(rpcCache.indexedDB).toBe(null);
    expect(rpcCache.crypto).toBe(null);

    expect(
        await rpcCache.read("table", "key", () => {
            expect.step("fallback");
            return Promise.resolve({ test: 123 });
        }),
    ).toEqual({ test: 123 });
    expect(
        await rpcCache.read("table", "key", () => {
            expect.step("fallback");
            return Promise.resolve({ test: 456 });
        }),
    ).toEqual({ test: 123 });
    expect.verifySteps(["fallback"]);

    expect(
        await rpcCache.read("t2", "key", () => Promise.resolve({ disk: 1 }), {
            type: "disk",
        }),
    ).toEqual({ disk: 1 });
    await tick();
    expect(
        await rpcCache.read("t2", "key", () => expect.step("should not be called"), {
            type: "disk",
        }),
    ).toEqual({ disk: 1 });

    rpcCache.invalidateByModel(["t2"], "res.partner");
    rpcCache.invalidate("table");
    rpcCache.invalidate();
    expect(
        await rpcCache.read("table", "key", () => Promise.resolve({ test: 789 })),
    ).toEqual({ test: 789 });
});

test("LRU eviction of a still-pending entry does not wedge later reads", async () => {
    const rpcCache = new RPCCache("mockRpc", 1, RAM_SECRET);
    const hung = new Deferred();
    rpcCache.read("t", "pending-key", () => hung);
    expect("t/pending-key" in rpcCache.pendingRequests).toBe(true);

    for (let i = 0; i < RAM_CACHE_MAX_ENTRIES; i++) {
        rpcCache.ramCache.write("t", `k${i}`, Promise.resolve(i));
    }
    expect(rpcCache.ramCache.ram.t["pending-key"]).toBe(undefined);
    expect("t/pending-key" in rpcCache.pendingRequests).toBe(true);

    const fresh = rpcCache.read("t", "pending-key", () => {
        expect.step("fresh fallback");
        return Promise.resolve("fresh");
    });
    expect.verifySteps(["fresh fallback"]);
    expect(await fresh).toBe("fresh");
});

test("RamCache: eviction keeps the model reverse index consistent", () => {
    const rc = new RPCCache("mockRpc", 1, RAM_SECRET).ramCache;
    rc.write("t", "victim", Promise.resolve("x"), "res.partner");
    for (let i = 0; i < RAM_CACHE_MAX_ENTRIES; i++) {
        rc.write("t", `k${i}`, Promise.resolve(i), "other.model");
    }
    expect(rc.read("t", "victim")).toBe(undefined);
    expect(rc.modelIndex.t.get("res.partner")).toBe(undefined);
    expect(rc.keyModel.t.victim).toBe(undefined);
    rc.invalidateByModel(["t"], "res.partner");
    expect(rc.lru.size).toBe(RAM_CACHE_MAX_ENTRIES);
});

test("piggyback refcount: abort(false) on the initiator leaves the piggybacked caller to settle", async () => {
    // Regression: the caller that started the fetch and the callers the cache
    // piggybacked on it shared ONE in-flight request with no refcounting, so
    // the initiator's silent abort evicted the pending entry and cancelled
    // the fetch -- the piggybacked caller's promise then stayed pending
    // FOREVER.
    rpc.setCache(new RPCCache("mockRpc", 1, RAM_SECRET));
    after(() => rpc.setCache(undefined));
    const fetchDef = new Deferred();
    let fetchCount = 0;
    mockFetch(() => {
        fetchCount++;
        return fetchDef;
    });

    const initiator = rpc("/test/", {}, { cache: true });
    const piggybacked = rpc("/test/", {}, { cache: true });
    let initiatorState = "pending";
    initiator.then(
        () => (initiatorState = "resolved"),
        () => (initiatorState = "rejected"),
    );
    await tick();
    expect(fetchCount).toBe(1);

    initiator.abort(false);
    await tick();

    fetchDef.resolve({ result: { ok: 1 } });
    expect(await piggybacked).toEqual({ ok: 1 });
    expect(initiatorState).toBe("pending"); // abort(false) stays silent
    // the fetched value completed into the cache: no re-fetch
    expect(await rpc("/test/", {}, { cache: true })).toEqual({ ok: 1 });
    expect(fetchCount).toBe(1);
});

test("piggyback refcount: abort(true) on the initiator rejects only that caller", async () => {
    // Regression: abort(true) rejected the shared request, so EVERY
    // piggybacked caller rejected along with the one that aborted.
    rpc.setCache(new RPCCache("mockRpc", 1, RAM_SECRET));
    after(() => rpc.setCache(undefined));
    const fetchDef = new Deferred();
    mockFetch(() => fetchDef);

    const initiator = rpc("/test/", {}, { cache: true });
    const piggybacked = rpc("/test/", {}, { cache: true });
    let piggybackedState = "pending";
    piggybacked.then(
        () => (piggybackedState = "resolved"),
        (/** @type {Error} */ e) => (piggybackedState = e.constructor.name),
    );
    await tick();

    initiator.abort(true);
    await expect(initiator).rejects.toThrow(ConnectionAbortedError);
    expect(piggybackedState).toBe("pending");

    fetchDef.resolve({ result: { ok: 2 } });
    expect(await piggybacked).toEqual({ ok: 2 });
});

test("piggyback refcount: the last caller out cancels the fetch and evicts the pending entry", async () => {
    const rpcCache = new RPCCache("mockRpc", 1, RAM_SECRET);
    rpc.setCache(rpcCache);
    after(() => rpc.setCache(undefined));
    const hung = new Deferred();
    /** @type {AbortSignal[]} */
    const signals = [];
    patchWithCleanup(browser, {
        fetch: /** @type {any} */ (
            (/** @type {string} */ _url, /** @type {RequestInit} */ { signal }) => {
                signals.push(/** @type {AbortSignal} */ (signal));
                expect.step(`fetch ${signals.length}`);
                if (signals.length === 1) {
                    return hung;
                }
                return Promise.resolve(
                    new Response(JSON.stringify({ result: { fresh: true } }), {
                        status: 200,
                        headers: { "Content-Type": "application/json" },
                    }),
                );
            }
        ),
    });

    const first = rpc("/test/", {}, { cache: true });
    const second = rpc("/test/", {}, { cache: true });
    await tick();
    expect.verifySteps(["fetch 1"]);
    expect(Object.keys(rpcCache.pendingRequests)).toHaveLength(1);

    first.abort(false);
    // `second` still subscribes: the fetch and the pending entry survive
    expect(signals[0].aborted).toBe(false);
    expect(Object.keys(rpcCache.pendingRequests)).toHaveLength(1);

    second.abort(true);
    await expect(second).rejects.toThrow(ConnectionAbortedError);
    expect(signals[0].aborted).toBe(true);
    expect(Object.keys(rpcCache.pendingRequests)).toHaveLength(0);

    // the dangling response must not complete into the (evicted) cache entry
    hung.resolve(
        new Response(JSON.stringify({ result: { stale: true } }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
        }),
    );
    await tick();
    await tick();
    expect(rpcCache.ramCache.read("/test/", buildKey("/test/", {}))).toBe(undefined);

    expect(await rpc("/test/", {}, { cache: true })).toEqual({ fresh: true });
    expect.verifySteps(["fetch 2"]);
});
