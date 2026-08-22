// @ts-check

import { expect, test } from "@odoo/hoot";
import { SpecialDataCache } from "@web/model/relational_model/special_data_cache";

test("stores and reads back", () => {
    const cache = new SpecialDataCache();
    expect(cache.has("a")).toBe(false);
    expect(cache.get("a")).toBe(undefined);
    cache.set("a", 1);
    expect(cache.has("a")).toBe(true);
    expect(cache.get("a")).toBe(1);
    expect(cache.size).toBe(1);
});

test("re-setting a key does not grow the cache", () => {
    const cache = new SpecialDataCache();
    cache.set("a", 1);
    cache.set("a", 2);
    expect(cache.size).toBe(1);
    expect(cache.get("a")).toBe(2);
});

test("delete removes an entry", () => {
    const cache = new SpecialDataCache();
    cache.set("a", 1);
    expect(cache.delete("a")).toBe(true);
    expect(cache.has("a")).toBe(false);
    expect(cache.delete("a")).toBe(false);
});

test("size never exceeds the limit", () => {
    const cache = new SpecialDataCache(3);
    for (let i = 0; i < 100; i++) {
        cache.set(`k${i}`, i);
    }
    expect(cache.size).toBe(3);
    expect(cache.has("k99")).toBe(true);
    expect(cache.has("k98")).toBe(true);
    expect(cache.has("k97")).toBe(true);
    expect(cache.has("k96")).toBe(false);
    expect(cache.has("k0")).toBe(false);
});

test("eviction is least-recently-used, not first-in", () => {
    const cache = new SpecialDataCache(3);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("c", 3);
    expect(cache.get("a")).toBe(1);
    cache.set("d", 4);
    expect(cache.has("b")).toBe(false);
    expect(cache.has("a")).toBe(true);
    expect(cache.has("c")).toBe(true);
    expect(cache.has("d")).toBe(true);
});

test("a re-set key is refreshed, not left stale in the eviction order", () => {
    const cache = new SpecialDataCache(2);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("a", 3);
    cache.set("c", 4);
    expect(cache.has("b")).toBe(false);
    expect(cache.get("a")).toBe(3);
    expect(cache.get("c")).toBe(4);
});
