// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv, onRpc } from "@web/../tests/web_test_helpers";
import {
    normalizeSelectedIds,
    quickSearchFilter,
    SEARCH_LIMIT,
    SEARCH_MORE_LIMIT,
    searchMoreLabel,
    searchMoreTitle,
    splitOverflow,
    webNameSearch,
} from "@web/components/autocomplete/name_search";

describe.current.tags("headless");

describe("webNameSearch", () => {
    test("calls web_name_search with the shared call shape", async () => {
        expect.assertions(4);
        onRpc("web_name_search", ({ model, kwargs }) => {
            expect(model).toBe("res.partner");
            expect(kwargs).toMatchObject({
                name: "aaa",
                operator: "ilike",
                domain: [["type", "=", "contact"]],
                limit: 8,
                specification: { display_name: {} },
            });
            expect(/** @type {any} */ (kwargs.context).blip).toBe("blop");
            return [];
        });
        const { services } = await makeMockEnv();
        const result = await webNameSearch(services.orm, "res.partner", {
            name: "aaa",
            domain: [["type", "=", "contact"]],
            limit: 8,
            context: { blip: "blop" },
        });
        expect(result).toEqual([]);
    });

    test("operator and specification can be overridden per caller", async () => {
        expect.assertions(2);
        onRpc("web_name_search", ({ kwargs }) => {
            expect(kwargs.operator).toBe("=");
            expect(kwargs.specification).toEqual({});
            return [];
        });
        const { services } = await makeMockEnv();
        await webNameSearch(services.orm, "res.partner", {
            name: "aaa",
            domain: [],
            limit: SEARCH_MORE_LIMIT,
            operator: "=",
            specification: {},
        });
    });

    test("the returned promise keeps the ORM's abort()", async () => {
        onRpc("web_name_search", () => []);
        const { services } = await makeMockEnv();
        const prom = webNameSearch(services.orm, "res.partner", {
            name: "",
            domain: [],
            limit: SEARCH_LIMIT + 1,
        });
        expect(typeof (/** @type {any} */ (prom).abort)).toBe("function");
        await prom;
    });
});

describe("splitOverflow", () => {
    const ids = (/** @type {number} */ n) =>
        Array.from({ length: n }, (_, i) => ({ id: i + 1 }));

    test("a result within the page is passed through, no overflow", () => {
        const records = ids(3);
        expect(splitOverflow(records, 7)).toEqual({ records, hasMore: false });
    });

    test("a result exactly at the page is not an overflow", () => {
        const records = ids(7);
        expect(splitOverflow(records, 7)).toEqual({ records, hasMore: false });
    });

    test("the limit + 1 probe record flags the overflow and is cut", () => {
        const { records, hasMore } = splitOverflow(ids(8), 7);
        expect(hasMore).toBe(true);
        expect(records).toEqual(ids(7));
    });

    test("an empty result is no overflow", () => {
        expect(splitOverflow([], 7)).toEqual({ records: [], hasMore: false });
    });
});

describe("dialog helpers", () => {
    test("quickSearchFilter scopes to the found ids", () => {
        const filter = quickSearchFilter("aaa", [1, 2]);
        expect(String(filter.description)).toBe("Quick search: aaa");
        expect(filter.domain).toEqual([["id", "in", [1, 2]]]);
    });

    test("quickSearchFilter takes an operator for the exclusion variant", () => {
        const filter = quickSearchFilter("", [3], "not in");
        expect(String(filter.description)).toBe("Quick search: ");
        expect(filter.domain).toEqual([["id", "not in", [3]]]);
    });

    test("searchMoreTitle names the field when it has a label", () => {
        expect(String(searchMoreTitle("Product"))).toBe("Search: Product");
        expect(String(searchMoreTitle(""))).toBe("Search");
        expect(String(searchMoreTitle(" "))).toBe("Search");
        expect(String(searchMoreTitle(undefined))).toBe("Search");
    });

    test("searchMoreLabel is the shared option label", () => {
        expect(searchMoreLabel().toString()).toBe("Search more...");
    });

    test("normalizeSelectedIds accepts one id or a list", () => {
        expect(normalizeSelectedIds(7)).toEqual([7]);
        expect(normalizeSelectedIds([7, 8])).toEqual([7, 8]);
    });
});
