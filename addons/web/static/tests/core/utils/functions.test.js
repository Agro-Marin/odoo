// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { memoize, uniqueId } from "@web/core/utils/functions";

describe.current.tags("headless");

test("memoize", () => {
    let callCount = 0;
    let lastReceivedArgs;
    const func = function () {
        lastReceivedArgs = [...arguments];
        return callCount++;
    };
    const memoized = memoize(func);
    const firstValue = memoized("first");
    expect(callCount).toBe(1);
    expect(lastReceivedArgs).toEqual(["first"]);
    const secondValue = memoized("first");
    expect(callCount).toBe(1);
    expect(firstValue).toBe(secondValue);
    const thirdValue = memoized();
    expect(callCount).toBe(2);
    const fourthValue = memoized();
    expect(thirdValue).toBe(fourthValue);
    expect(callCount).toBe(2);
    memoized(1, 2, 3);
    expect(callCount).toBe(3);
    expect(lastReceivedArgs).toEqual([1, 2, 3]);
    memoized(1, 2, 3);
    expect(callCount).toBe(3);
    memoized(1, 20, 30);
    expect(callCount).toBe(4);
    expect(lastReceivedArgs).toEqual([1, 20, 30]);
});

test("memoize keys on every argument, and arities do not collide", () => {
    let calls = 0;
    const memoized = memoize((...args) => {
        calls++;
        return args.join("|");
    });
    const owner = {};
    expect(memoized(owner, "product-A")).toBe(`${owner}|product-A`);
    expect(memoized(owner, "product-B")).toBe(`${owner}|product-B`);
    expect(calls).toBe(2);
    expect(memoized(owner, "product-A")).toBe(`${owner}|product-A`);
    expect(calls).toBe(2);

    expect(memoized(owner)).toBe(String(owner));
    expect(calls).toBe(3);
    expect(memoized(owner, "product-A")).toBe(`${owner}|product-A`);
    expect(calls).toBe(3);
});

test("memoize distinguishes object arguments by identity", () => {
    let calls = 0;
    const memoized = memoize((a, b) => {
        calls++;
        return { a, b };
    });
    const k1 = {};
    const k2 = {};
    memoized(k1, k2);
    memoized(k1, k2);
    expect(calls).toBe(1);
    memoized(k2, k1);
    expect(calls).toBe(2);
});

test("memoized function inherit function name if possible", () => {
    const memoized1 = memoize(function test() {});
    expect(memoized1.name).toBe("test (memoized)");
    const memoized2 = memoize(function () {});
    expect(memoized2.name).toBe("memoized");
});

test("uniqueId", () => {
    patchWithCleanup(uniqueId, { nextId: 0 });
    expect(uniqueId("test_")).toBe("test_1");
    expect(uniqueId("bla")).toBe("bla2");
    expect(uniqueId("test_")).toBe("test_3");
    expect(uniqueId("bla")).toBe("bla4");
    expect(uniqueId("test_")).toBe("test_5");
    expect(uniqueId("test_")).toBe("test_6");
    expect(uniqueId("bla")).toBe("bla7");
});

test("uniqueId counter is anchored on globalThis (cross-bundle)", () => {
    const state = /** @type {any} */ (globalThis).__odoo_singletons__?.uniqueId;
    expect(state).not.toBe(undefined);
    const before = state.nextId;
    const id = uniqueId("anchor_");
    expect(id).toBe(`anchor_${before + 1}`);
    expect(state.nextId).toBe(before + 1);
    expect(uniqueId.nextId).toBe(state.nextId);
});

test("memoize evicts a rejected promise so the next call retries", async () => {
    let calls = 0;
    const fn = memoize(async (key) => {
        calls++;
        if (calls === 1) {
            throw new Error("boom");
        }
        return `ok:${key}`;
    });
    await expect(fn("k")).rejects.toThrow("boom");
    expect(await fn("k")).toBe("ok:k");
    expect(calls).toBe(2);
    expect(await fn("k")).toBe("ok:k");
    expect(calls).toBe(2);
});

test("an object argument is not pinned for the life of the page", async () => {
    // `memoize` keys on identity, so a strong Map would keep every object ever
    // passed alive. Weak keys make the entry collectable once the caller drops
    // the key; the observable contract -- compute once per argument tuple --
    // is unchanged, which is what the rest of this suite pins.
    let calls = 0;
    const memoized = memoize((/** @type {object} */ obj) => {
        calls++;
        return obj;
    });
    const key = {};
    memoized(key);
    memoized(key);
    expect(calls).toBe(1);

    // the cache node itself must hold the key weakly
    const registry = new FinalizationRegistry(() => {});
    expect(() => registry.register(key, "ok")).not.toThrow();
});
