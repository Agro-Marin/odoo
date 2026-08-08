// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import {
    isPlainObject,
    readJSONStorage,
    writeJSONStorage,
} from "@web/core/browser/storage_json";

describe.current.tags("headless");

const KEY = "test.storage_json";

/**
 * Replace `browser.localStorage` with a stub whose four methods can each be
 * made to throw, so the private-mode / quota paths are exercised for real
 * rather than assumed.
 *
 * @param {{ store?: Record<string, string>, throwOn?: string[] }} [options]
 */
function mockStorage({ store = {}, throwOn = [] } = {}) {
    /** @type {any[]} */
    const calls = [];
    const guard = (/** @type {string} */ name) => {
        calls.push(name);
        if (throwOn.includes(name)) {
            throw new Error(`localStorage.${name} unavailable`);
        }
    };
    patchWithCleanup(browser, {
        localStorage: {
            getItem(key) {
                guard("getItem");
                return key in store ? store[key] : null;
            },
            setItem(key, value) {
                guard("setItem");
                store[key] = String(value);
            },
            removeItem(key) {
                guard("removeItem");
                delete store[key];
            },
        },
    });
    return { store, calls };
}

test("a missing key yields the fallback", () => {
    mockStorage();
    expect(readJSONStorage(KEY, { fallback: [] })).toEqual([]);
});

test("a well-formed value round-trips through write then read", () => {
    mockStorage();
    expect(writeJSONStorage(KEY, { a: 1, b: [2, 3] })).toBe(true);
    expect(readJSONStorage(KEY, { fallback: {} })).toEqual({ a: 1, b: [2, 3] });
});

test("unparsable JSON yields the fallback instead of throwing", () => {
    const { store } = mockStorage({ store: { [KEY]: "{not json" } });
    expect(readJSONStorage(KEY, { fallback: {} })).toEqual({});
    expect(KEY in store).toBe(true, {
        message: "left in place without clearOnInvalid",
    });
});

test("valid JSON of the wrong shape is rejected by validate", () => {
    // The failure mode a bare try/catch misses: `JSON.parse` succeeds and the
    // caller only explodes later, on every render.
    for (const raw of ["null", "42", '"a string"', "[1,2]", "true"]) {
        mockStorage({ store: { [KEY]: raw } });
        expect(readJSONStorage(KEY, { fallback: {}, validate: isPlainObject })).toEqual(
            {},
            { message: `raw=${raw}` },
        );
    }
});

test("an array passes an Array.isArray validate but a plain object does not", () => {
    mockStorage({ store: { [KEY]: '[{"userId":1}]' } });
    expect(readJSONStorage(KEY, { fallback: [], validate: Array.isArray })).toEqual([
        { userId: 1 },
    ]);
    mockStorage({ store: { [KEY]: '{"userId":1}' } });
    expect(readJSONStorage(KEY, { fallback: [], validate: Array.isArray })).toEqual([]);
});

test("clearOnInvalid evicts a bad value, and only a bad value", () => {
    const bad = mockStorage({ store: { [KEY]: "null" } });
    readJSONStorage(KEY, {
        fallback: [],
        validate: Array.isArray,
        clearOnInvalid: true,
    });
    expect(KEY in bad.store).toBe(false);

    const good = mockStorage({ store: { [KEY]: "[1]" } });
    readJSONStorage(KEY, {
        fallback: [],
        validate: Array.isArray,
        clearOnInvalid: true,
    });
    expect(KEY in good.store).toBe(true);
});

test("a throwing getItem yields the fallback (private mode / sandboxed iframe)", () => {
    mockStorage({ throwOn: ["getItem"] });
    expect(readJSONStorage(KEY, { fallback: { ok: true } })).toEqual({ ok: true });
});

test("a throwing removeItem during eviction still yields the fallback", () => {
    mockStorage({ store: { [KEY]: "null" }, throwOn: ["removeItem"] });
    expect(
        readJSONStorage(KEY, {
            fallback: [],
            validate: Array.isArray,
            clearOnInvalid: true,
        }),
    ).toEqual([]);
});

test("a throwing setItem reports failure rather than propagating (quota)", () => {
    mockStorage({ throwOn: ["setItem"] });
    expect(writeJSONStorage(KEY, { a: 1 })).toBe(false);
});

test("isPlainObject rejects the values typeof 'object' lets through", () => {
    expect(isPlainObject({})).toBe(true);
    expect(isPlainObject({ a: 1 })).toBe(true);
    expect(isPlainObject(null)).toBe(false);
    expect(isPlainObject([])).toBe(false);
    expect(isPlainObject("s")).toBe(false);
    expect(isPlainObject(0)).toBe(false);
    expect(isPlainObject(undefined)).toBe(false);
});
