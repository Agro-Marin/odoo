// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Cache } from "@web/core/utils/collections/cache";

describe.current.tags("headless");

describe("Cache", () => {
    test("read() computes and stores value on first access", () => {
        let callCount = 0;
        const cache = new Cache((...args) => {
            callCount++;
            return args.join("-");
        });
        expect(cache.read("a")).toBe("a");
        expect(callCount).toBe(1);
        // Second read should return cached value without recomputing
        expect(cache.read("a")).toBe("a");
        expect(callCount).toBe(1);
    });

    test("read() with nested key path", () => {
        let callCount = 0;
        const cache = new Cache((...args) => {
            callCount++;
            return args.join(":");
        });
        expect(cache.read("model", "field", "key")).toBe("model:field:key");
        expect(callCount).toBe(1);
        // Same path returns cached
        expect(cache.read("model", "field", "key")).toBe("model:field:key");
        expect(callCount).toBe(1);
        // Different path computes new value
        expect(cache.read("model", "field", "other")).toBe("model:field:other");
        expect(callCount).toBe(2);
    });

    test("read() with custom getKey function", () => {
        let callCount = 0;
        const cache = new Cache(
            (a, b) => {
                callCount++;
                return a + b;
            },
            (a, b) => `${a},${b}`,
        );
        expect(cache.read(1, 2)).toBe(3);
        expect(callCount).toBe(1);
        expect(cache.read(1, 2)).toBe(3);
        expect(callCount).toBe(1);
        expect(cache.read(2, 1)).toBe(3);
        expect(callCount).toBe(2);
    });

    test("clear() removes a single entry by path", () => {
        let callCount = 0;
        const cache = new Cache(() => ++callCount);
        cache.read("a");
        cache.read("b");
        expect(callCount).toBe(2);
        cache.clear("a");
        // "a" was cleared, must recompute
        cache.read("a");
        expect(callCount).toBe(3);
        // "b" is still cached
        cache.read("b");
        expect(callCount).toBe(3);
    });

    test("clear() with nested key path", () => {
        let callCount = 0;
        const cache = new Cache(() => ++callCount);
        cache.read("x", "y");
        cache.read("x", "z");
        expect(callCount).toBe(2);
        cache.clear("x", "y");
        cache.read("x", "y");
        expect(callCount).toBe(3);
        // Other nested key still cached
        cache.read("x", "z");
        expect(callCount).toBe(3);
    });

    test("invalidate() flushes entire cache", () => {
        let callCount = 0;
        const cache = new Cache(() => ++callCount);
        cache.read("a");
        cache.read("b");
        expect(callCount).toBe(2);
        cache.invalidate();
        cache.read("a");
        cache.read("b");
        expect(callCount).toBe(4);
    });

    test("caches falsy values correctly", () => {
        const values = [0, "", false, null, undefined];
        let idx = 0;
        const cache = new Cache(() => values[idx++]);
        for (const val of values) {
            const key = String(idx);
            const result = cache.read(key);
            expect(result).toBe(val);
            // Second read returns same falsy value
            expect(cache.read(key)).toBe(val);
        }
        // getValue was called exactly once per key
        expect(idx).toBe(values.length);
    });

    test("clear() on non-existent key is a no-op", () => {
        const cache = new Cache(() => 1);
        cache.read("a");
        // Should not throw
        cache.clear("nonexistent");
        // Existing entry still intact
        let callCount = 0;
        const cache2 = new Cache(() => ++callCount);
        cache2.read("a");
        cache2.clear("b");
        cache2.read("a");
        expect(callCount).toBe(1);
    });

    test("getKey collapses different paths to same cache slot", () => {
        let callCount = 0;
        const cache = new Cache(
            () => ++callCount,
            // Collapse all paths to same key
            () => "same",
        );
        cache.read("a");
        cache.read("b");
        cache.read("c");
        // All resolve to the same key, so getValue called only once
        expect(callCount).toBe(1);
    });

    test("throws on a non-primitive path segment when getKey is absent", () => {
        const cache = new Cache((x) => x);
        // Objects/functions would all coerce to "[object Object]" and collide
        // into one slot; null/undefined collide with "null"/"undefined".
        expect(() => cache.read({})).toThrow(/invalid path segment/);
        expect(() => cache.read("model", [1, 2])).toThrow(/invalid path segment/);
        expect(() => cache.read(null)).toThrow(/invalid path segment/);
        expect(() => cache.read(undefined)).toThrow(/invalid path segment/);
        // Primitive segments are still accepted.
        expect(cache.read("ok")).toBe("ok");
        expect(cache.read(1)).toBe(1);
    });

    test("object path segments are allowed when a getKey is provided", () => {
        const cache = new Cache((o) => o.v, JSON.stringify);
        expect(cache.read({ v: 5 })).toBe(5);
        expect(cache.read({ v: 5 })).toBe(5);
    });

    test("read() self-evicts a rejected promise instead of poisoning the slot", async () => {
        let calls = 0;
        const cache = new Cache(async (k) => {
            calls++;
            if (calls === 1) {
                throw new Error("boom");
            }
            return "recovered";
        });
        await expect(cache.read("k")).rejects.toThrow(/boom/);
        // Let the self-eviction .catch run.
        await Promise.resolve();
        // The rejected slot was evicted, so the next read recomputes.
        expect(await cache.read("k")).toBe("recovered");
        expect(calls).toBe(2);
    });

    test("read() keeps a resolved promise cached", async () => {
        let calls = 0;
        const cache = new Cache(async () => {
            calls++;
            return "v";
        });
        expect(await cache.read("k")).toBe("v");
        expect(await cache.read("k")).toBe("v");
        expect(calls).toBe(1);
    });
});
