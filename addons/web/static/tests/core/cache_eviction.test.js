// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot";
import { mockIndexedDBForTests } from "@web/../tests/_framework/mock_indexed_db.hoot";
import { RAM_CACHE_MAX_ENTRIES, RPCCache } from "@web/core/network/rpc_cache";
import { Cache } from "@web/core/utils/collections/cache";

mockIndexedDBForTests();
describe.current.tags("headless");

describe("Cache.clear", () => {
    test("clearing a path that was never written allocates nothing", () => {
        const cache = new Cache((a, b) => `${a}/${b}`);
        cache.clear("never", "registered");
        // An eviction call must not make the cache bigger.
        expect(Object.keys(cache.cache)).toEqual([]);
    });

    test("clearing a path that WAS written still removes it", () => {
        const cache = new Cache((a, b) => `${a}/${b}`);
        expect(cache.read("a", "b")).toBe("a/b");
        expect(Object.keys(cache.cache)).toEqual(["a"]);
        cache.clear("a", "b");
        expect(cache.cache["a"]["b"]).toBe(undefined);
    });

    test("clearing one branch leaves its siblings intact", () => {
        const cache = new Cache((a, b) => `${a}/${b}`);
        cache.read("a", "x");
        cache.read("a", "y");
        cache.clear("a", "x");
        expect(cache.cache["a"]["x"]).toBe(undefined);
        expect(cache.cache["a"]["y"]).toBe("a/y");
    });

    test("a single-segment path still works", () => {
        const cache = new Cache((a) => `v:${a}`);
        expect(cache.read("k")).toBe("v:k");
        cache.clear("k");
        expect(cache.cache["k"]).toBe(undefined);
        cache.clear("absent");
    });
});

describe("RPCCache in-flight join", () => {
    test("a live in-flight request is joined, not refetched", async () => {
        const cache = new RPCCache("probe-join", 1, null); // RAM-only
        let fetches = 0;
        const blocker = new Deferred();

        const first = cache.read("tbl", "hot", () => {
            fetches++;
            return blocker;
        });
        const second = cache.read("tbl", "hot", () => {
            fetches++;
            return Promise.resolve("second");
        });

        blocker.resolve("first");
        expect(await first).toBe("first");
        expect(await second).toBe("first");
        expect(fetches).toBe(1);
    });

    test("an in-flight request the LRU evicted is refetched, by design", async () => {
        // Complements "LRU eviction of a still-pending entry does not wedge
        // later reads" in network/rpc_cache.test.js, from the caller's side: the
        // duplicate fetch is the escape hatch, not a defect. Joining on the
        // pending request alone would hand this reader a promise that never
        // settles whenever the evicted request is a hung one.
        const cache = new RPCCache("probe-evicted", 1, null);
        let fetches = 0;
        const hung = new Deferred();
        cache.read("tbl", "hot", () => {
            fetches++;
            return hung;
        });
        for (let i = 0; i < RAM_CACHE_MAX_ENTRIES + 5; i++) {
            cache.ramCache.write("tbl", `filler${i}`, Promise.resolve(i));
        }
        expect(cache.ramCache.read("tbl", "hot")).toBe(undefined);

        const second = cache.read("tbl", "hot", () => {
            fetches++;
            return Promise.resolve("second");
        });
        expect(await second).toBe("second");
        expect(fetches).toBe(2);
    });

    test("a reader after settle re-reads from RAM without refetching", async () => {
        const cache = new RPCCache("probe-settled", 1, null);
        let fetches = 0;
        const fallback = () => {
            fetches++;
            return Promise.resolve("value");
        };
        expect(await cache.read("tbl", "k", fallback)).toBe("value");
        expect(await cache.read("tbl", "k", fallback)).toBe("value");
        expect(fetches).toBe(1);
    });
});
