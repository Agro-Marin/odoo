// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { groupBy, sortBy } from "@web/core/utils/collections/arrays";

describe.current.tags("headless");

describe("the empty-string key is a key", () => {
    const rows = [{ "": "z" }, { "": "y" }];

    test("sortBy sorts by it instead of silently no-op'ing", () => {
        expect(sortBy(rows, "").map((r) => r[""])).toEqual(["y", "z"]);
    });

    test("groupBy groups by it instead of one merged bucket", () => {
        expect(Object.keys(groupBy(rows, "")).sort()).toEqual(["y", "z"]);
    });
});

describe("the falsy NUMBER 0 is rejected, like any other number", () => {
    test("sortBy", () => {
        expect(() => sortBy([{ 0: "b" }], 0)).toThrow(
            /Expected criterion of type 'string' or 'function' and got 'number'/,
        );
    });

    test("groupBy", () => {
        expect(() => groupBy([{ 0: "b" }], 0)).toThrow(
            /Expected criterion of type 'string' or 'function' and got 'number'/,
        );
    });
});

describe("absence still means the element itself", () => {
    test("omitted, undefined and null are all 'no criterion'", () => {
        expect(sortBy(["b", "a", "c"])).toEqual(["a", "b", "c"]);
        expect(sortBy(["b", "a"], undefined)).toEqual(["a", "b"]);
        expect(sortBy(["b", "a"], null)).toEqual(["a", "b"]);
        expect(Object.keys(groupBy(["b", "a"], null)).sort()).toEqual(["a", "b"]);
    });

    test("string keys and functions are unaffected", () => {
        expect(sortBy([{ k: "b" }, { k: "a" }], "k").map((r) => r.k)).toEqual([
            "a",
            "b",
        ]);
        expect(sortBy([3, 1, 2], (n) => -n)).toEqual([3, 2, 1]);
    });
});
