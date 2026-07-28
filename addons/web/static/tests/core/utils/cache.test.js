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
        expect(cache.read("model", "field", "key")).toBe("model:field:key");
        expect(callCount).toBe(1);
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
        cache.read("a");
        expect(callCount).toBe(3);
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
            expect(cache.read(key)).toBe(val);
        }
        expect(idx).toBe(values.length);
    });

    test("clear() on non-existent key is a no-op", () => {
        const cache = new Cache(() => 1);
        cache.read("a");
        cache.clear("nonexistent");
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
            () => "same",
        );
        cache.read("a");
        cache.read("b");
        cache.read("c");
        expect(callCount).toBe(1);
    });

    test("throws on a non-primitive path segment when getKey is absent", () => {
        const cache = new Cache((x) => x);
        expect(() => cache.read({})).toThrow(/invalid path segment/);
        expect(() => cache.read("model", [1, 2])).toThrow(/invalid path segment/);
        expect(() => cache.read(null)).toThrow(/invalid path segment/);
        expect(() => cache.read(undefined)).toThrow(/invalid path segment/);
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
        await Promise.resolve();
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
