// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { BreadcrumbCache } from "@web/webclient/actions/breadcrumb_cache";

describe.current.tags("headless");

/** @param {BreadcrumbCache} cache */
const keysOf = (cache) => [...cache._entries.keys()];

test("evicts the coldest entry when full", async () => {
    const cache = new BreadcrumbCache(3);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("c", 3);
    expect(cache.size).toBe(3);

    cache.set("d", 4);

    expect(cache.size).toBe(3);
    expect(cache.has("a")).toBe(false);
    expect(keysOf(cache)).toEqual(["b", "c", "d"]);
});

test("a read marks an entry as recently used", async () => {
    const cache = new BreadcrumbCache(3);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("c", 3);

    expect(cache.get("a")).toBe(1);
    cache.set("d", 4);

    expect(cache.has("a")).toBe(true);
    expect(cache.has("b")).toBe(false);
    expect(keysOf(cache)).toEqual(["c", "a", "d"]);
});

test("overwriting an existing key does not evict", async () => {
    const cache = new BreadcrumbCache(2);
    cache.set("a", 1);
    cache.set("b", 2);

    cache.set("a", 99);

    expect(cache.size).toBe(2);
    expect(cache.get("a")).toBe(99);
    expect(cache.has("b")).toBe(true);
});

test("get on a missing key returns undefined without inserting", async () => {
    const cache = new BreadcrumbCache(2);
    expect(cache.get("nope")).toBe(undefined);
    expect(cache.size).toBe(0);
});

test("delete removes an entry and frees its slot", async () => {
    const cache = new BreadcrumbCache(2);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.delete("a");
    expect(cache.size).toBe(1);

    cache.set("c", 3);
    expect(keysOf(cache)).toEqual(["b", "c"]);
});

test("a cached in-flight promise is returned as-is", async () => {
    const cache = new BreadcrumbCache(2);
    const pending = Promise.resolve({ display_name: "Partner" });
    cache.set("k", pending);

    expect(cache.get("k")).toBe(pending);
    expect(await cache.get("k")).toEqual({ display_name: "Partner" });
});

test("touch keeps an entry alive without consuming it", () => {
    const cache = new BreadcrumbCache(2);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.touch("a");
    cache.set("c", 3);

    expect(cache.has("a")).toBe(true);
    expect(cache.has("b")).toBe(false);
    expect(cache.get("a")).toBe(1);
});
