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
        expect(Object.keys(cache.cache)).toEqual([]);
    });

    test("clearing a path that WAS written still removes it", () => {
        const cache = new Cache((a, b) => expect.step(`${a}/${b}`));
        cache.read("a", "b");
        cache.read("a", "b");
        expect.verifySteps(["a/b"]);
        cache.clear("a", "b");
        cache.read("a", "b");
        expect.verifySteps(["a/b"]);
    });

    test("clearing one branch leaves its siblings intact", () => {
        const cache = new Cache((a, b) => expect.step(`${a}/${b}`));
        cache.read("a", "x");
        cache.read("a", "y");
        expect.verifySteps(["a/x", "a/y"]);
        cache.clear("a", "x");
        cache.read("a", "y");
        expect.verifySteps([]);
        cache.read("a", "x");
        expect.verifySteps(["a/x"]);
    });

    test("a single-segment path still works", () => {
        const cache = new Cache((a) => expect.step(`v:${a}`));
        cache.read("k");
        expect.verifySteps(["v:k"]);
        cache.clear("k");
        cache.read("k");
        expect.verifySteps(["v:k"]);
        cache.clear("absent");
    });
});

describe("Cache path arities", () => {
    test("a value stored at one arity is not walked into by a longer path", () => {
        const cache = new Cache((...path) => ({ got: path.join("/") }));
        const shallow = cache.read("a");
        expect(cache.read("a", "b")).toEqual({ got: "a/b" });
        expect(shallow).toEqual({ got: "a" });
        expect(cache.read("a")).toBe(shallow);
    });

    test("a cached falsy value survives a longer path through the same segment", () => {
        const cache = new Cache((...path) => (path.length === 1 ? 0 : "deep"));
        expect(cache.read("x")).toBe(0);
        expect(cache.read("x", "y")).toBe("deep");
        expect(cache.read("x")).toBe(0);
    });

    test("clearing one arity leaves the other arities alone", () => {
        const cache = new Cache((...path) => expect.step(path.join("/")));
        cache.read("a");
        cache.read("a", "b");
        expect.verifySteps(["a", "a/b"]);
        cache.clear("a");
        cache.read("a", "b");
        expect.verifySteps([]);
        cache.read("a");
        expect.verifySteps(["a"]);
    });
});

describe("RPCCache in-flight join", () => {
    test("a live in-flight request is joined, not refetched", async () => {
        const cache = new RPCCache("probe-join", 1, null);
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
