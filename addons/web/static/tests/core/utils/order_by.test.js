// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { orderByToString, stringToOrderBy } from "@web/core/utils/order_by";

describe.current.tags("headless");

describe("orderByToString", () => {
    test("empty array", () => {
        expect(orderByToString([])).toBe("");
    });

    test("single ascending term", () => {
        expect(orderByToString([{ name: "date", asc: true }])).toBe("date ASC");
    });

    test("single descending term", () => {
        expect(orderByToString([{ name: "date", asc: false }])).toBe("date DESC");
    });

    test("missing asc defaults to DESC (falsy)", () => {
        expect(orderByToString([{ name: "date" }])).toBe("date DESC");
    });

    test("multiple terms", () => {
        expect(
            orderByToString([
                { name: "date", asc: false },
                { name: "name", asc: true },
                { name: "id", asc: true },
            ]),
        ).toBe("date DESC, name ASC, id ASC");
    });
});

describe("stringToOrderBy", () => {
    test("falsy input returns empty array", () => {
        expect(stringToOrderBy("")).toEqual([]);
        expect(stringToOrderBy(null)).toEqual([]);
        expect(stringToOrderBy(undefined)).toEqual([]);
        expect(stringToOrderBy(false)).toEqual([]);
    });

    test("single field with ASC", () => {
        expect(stringToOrderBy("name ASC")).toEqual([{ name: "name", asc: true }]);
    });

    test("single field with DESC", () => {
        expect(stringToOrderBy("name DESC")).toEqual([{ name: "name", asc: false }]);
    });

    test("single field without direction defaults to ASC", () => {
        expect(stringToOrderBy("name")).toEqual([{ name: "name", asc: true }]);
    });

    test("case insensitive direction", () => {
        expect(stringToOrderBy("name asc")).toEqual([{ name: "name", asc: true }]);
        expect(stringToOrderBy("name desc")).toEqual([{ name: "name", asc: false }]);
        expect(stringToOrderBy("name Asc")).toEqual([{ name: "name", asc: true }]);
    });

    test("multiple terms", () => {
        expect(stringToOrderBy("date DESC, name ASC")).toEqual([
            { name: "date", asc: false },
            { name: "name", asc: true },
        ]);
    });

    test("roundtrip preserves semantics", () => {
        const terms = [
            { name: "date", asc: false },
            { name: "name", asc: true },
            { name: "id", asc: true },
        ];
        expect(stringToOrderBy(orderByToString(terms))).toEqual(terms);
    });
});
