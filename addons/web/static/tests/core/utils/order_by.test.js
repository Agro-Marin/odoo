// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    InvalidOrderError,
    orderByToString,
    stringToOrderBy,
} from "@web/core/utils/order_by";

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

    test("missing asc defaults to ASC", () => {
        expect(orderByToString([{ name: "date" }])).toBe("date ASC");
        expect(orderByToString([{ name: "date", asc: undefined }])).toBe("date ASC");
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

    test("empty terms are rejected, not silently kept", () => {
        expect(() => stringToOrderBy("id desc,")).toThrow(InvalidOrderError);
        expect(() => stringToOrderBy(",")).toThrow(InvalidOrderError);
        expect(() => stringToOrderBy(" ")).toThrow(InvalidOrderError);
        expect(() => stringToOrderBy("a, ,b")).toThrow(InvalidOrderError);
    });

    test("an unrecognised direction is rejected, not read as DESC", () => {
        expect(() => stringToOrderBy("id ASCENDING")).toThrow(InvalidOrderError);
        expect(() => stringToOrderBy("id ASCII")).toThrow(InvalidOrderError);
        expect(() => stringToOrderBy("id up")).toThrow(InvalidOrderError);
    });

    test("more than two tokens in a term is still rejected", () => {
        expect(() => stringToOrderBy("id desc extra")).toThrow(InvalidOrderError);
    });

    test("valid input is unaffected by the added validation", () => {
        expect(stringToOrderBy("  date   DESC ,  name  ")).toEqual([
            { name: "date", asc: false },
            { name: "name", asc: true },
        ]);
    });
});
