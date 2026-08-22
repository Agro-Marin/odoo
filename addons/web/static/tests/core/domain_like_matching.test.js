// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";

describe.current.tags("headless");

/**
 * @param {any} value
 * @param {string} operator
 * @param {any} pattern
 */
function matches(value, operator, pattern) {
    return new Domain([["ref", operator, pattern]]).contains({ ref: value });
}

describe("ilike folds the way the server folds", () => {
    const CASES = [
        ["Ø", "o"],
        ["Œdipe", "oe"],
        ["Großkreutz", "ss"],
        ["Łódź", "l"],
        ["José", "jose"],
        ["Æon", "aeon"],
        ["Đorđe", "dorde"],
    ];
    for (const [value, pattern] of CASES) {
        test(`'${value}' ilike '${pattern}'`, () => {
            expect(matches(value, "ilike", pattern)).toBe(true);
            expect(matches(value, "not ilike", pattern)).toBe(false);
        });
    }

    test("=ilike anchors the folded pattern", () => {
        expect(matches("Großkreutz", "=ilike", "grosskreutz")).toBe(true);
        expect(matches("Großkreutz", "=ilike", "grosskreut")).toBe(false);
        expect(matches("Großkreutz", "=ilike", "gross%")).toBe(true);
    });

    test("like stays case-sensitive and does NOT fold", () => {
        expect(matches("ABC", "like", "abc")).toBe(false);
        expect(matches("Großkreutz", "like", "ss")).toBe(false);
        expect(matches("Großkreutz", "like", "ß")).toBe(true);
    });
});

describe("LIKE pattern semantics", () => {
    test("% matches any run, _ matches exactly one", () => {
        expect(matches("abc", "like", "a%c")).toBe(true);
        expect(matches("ac", "like", "a%c")).toBe(true);
        expect(matches("abc", "like", "a_c")).toBe(true);
        expect(matches("ac", "like", "a_c")).toBe(false);
    });

    test("backslash escapes the wildcards", () => {
        expect(matches("a%b", "like", "a\\%b")).toBe(true);
        expect(matches("axb", "like", "a\\%b")).toBe(false);
        expect(matches("a_b", "like", "a\\_b")).toBe(true);
        expect(matches("axb", "like", "a\\_b")).toBe(false);
    });

    test("consecutive % collapse (%% is exactly %)", () => {
        expect(matches("abc", "=like", "a%%%c")).toBe(true);
        expect(matches("abc", "=like", "%%%")).toBe(true);
    });

    test("=like anchors, like does not", () => {
        expect(matches("abc", "=like", "ab")).toBe(false);
        expect(matches("abc", "=like", "abc")).toBe(true);
        expect(matches("abc", "like", "b")).toBe(true);
    });

    test("empty pattern: ilike matches everything, =like only the unset", () => {
        expect(matches("abc", "ilike", "")).toBe(true);
        expect(matches(false, "=like", "")).toBe(true);
        expect(matches("abc", "=like", "")).toBe(false);
    });

    test("unset field compares as the empty string", () => {
        expect(matches(false, "ilike", "a")).toBe(false);
        expect(matches(false, "not ilike", "a")).toBe(true);
    });

    test("a field absent from the record never matches", () => {
        expect(new Domain([["nope", "ilike", "a"]]).contains({})).toBe(false);
        expect(new Domain([["nope", "not ilike", "a"]]).contains({})).toBe(true);
    });

    test("a numeric operand is accepted on both sides", () => {
        expect(matches(1234, "like", "23")).toBe(true);
        expect(matches("x1234y", "like", 234)).toBe(true);
    });
});

describe("LIKE matching is linear, not exponential", () => {
    test("many wildcards against a repetitive subject stay fast", () => {
        const pattern = "%a".repeat(10) + "Z";
        const subject = "axyz".repeat(60);
        const start = performance.now();
        expect(matches(subject, "ilike", pattern)).toBe(false);
        expect(performance.now() - start).toBeLessThan(500);
    });
});

describe("Domain.compile / Domain.filter", () => {
    test("filter selects the same records as contains", () => {
        const records = [
            { ref: "widget A", qty: 10 },
            { ref: "gadget B", qty: 90 },
            { ref: "widget C", qty: 90 },
        ];
        const domain = new Domain(["&", ["qty", ">", 50], ["ref", "ilike", "widget"]]);
        expect(domain.filter(records)).toEqual([records[2]]);
        expect(records.filter((r) => domain.contains(r))).toEqual(
            domain.filter(records),
        );
    });

    test("compile returns a reusable predicate", () => {
        const predicate = new Domain([["ref", "=", "x"]]).compile();
        expect(predicate({ ref: "x" })).toBe(true);
        expect(predicate({ ref: "y" })).toBe(false);
    });

    test("a record-dependent domain is not hoisted and still resolves per record", () => {
        const domain = new Domain('[("a", "=", qty)]');
        expect(domain.contains({ a: 5, qty: 5 })).toBe(true);
        expect(domain.contains({ a: 5, qty: 6 })).toBe(false);
        expect(domain.contains({ a: 7, qty: 7 })).toBe(true);
    });

    test("short-circuiting still skips a malformed leaf it never reaches", () => {
        const domain = new Domain([
            "|",
            ["a", "=", 1],
            ["b", /** @type {any} */ (5), 1],
        ]);
        expect(domain.contains({ a: 1, b: 1 })).toBe(true);
    });
});
