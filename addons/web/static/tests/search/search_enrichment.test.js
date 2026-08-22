// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DateTime } from "@web/core/l10n/luxon";
import {
    enrichSearchItem,
    indexQueryBySearchItem,
} from "@web/search/search_enrichment";
import { getIntervalOptions } from "@web/search/utils/dates";

describe.current.tags("headless");

const INTERVALS = getIntervalOptions();
const MOMENT = DateTime.fromISO("2023-05-15T00:00:00");

describe("indexQueryBySearchItem", () => {
    test("groups the query elements under their search item", () => {
        const query = [
            { searchItemId: 1, generatorId: "month" },
            { searchItemId: 2 },
            { searchItemId: 1, generatorId: "year" },
        ];
        const index = indexQueryBySearchItem(query);
        expect([...index.keys()]).toEqual([1, 2]);
        expect(index.get(1)).toEqual([
            { searchItemId: 1, generatorId: "month" },
            { searchItemId: 1, generatorId: "year" },
        ]);
        expect(index.get(2)).toEqual([{ searchItemId: 2 }]);
    });

    test("keeps query order within a search item", () => {
        const query = [
            { searchItemId: 1, generatorId: "year-1" },
            { searchItemId: 1, generatorId: "month" },
        ];
        expect(
            indexQueryBySearchItem(query)
                .get(1)
                .map((/** @type {any} */ q) => q.generatorId),
        ).toEqual(["year-1", "month"]);
    });

    test("an empty query indexes to an empty map", () => {
        expect(indexQueryBySearchItem([]).size).toBe(0);
    });
});

describe("enrichSearchItem", () => {
    /**
     * @param {Record<string, any>} searchItem
     * @param {Record<string, any>[]} query
     * @returns {any}
     */
    const enrich = (searchItem, query = []) =>
        enrichSearchItem(
            /** @type {any} */ (searchItem),
            /** @type {any} */ (query),
            MOMENT,
            INTERVALS,
        );

    test("an item with no query element is inactive and otherwise unchanged", () => {
        const item = { id: 1, type: "filter", description: "F", domain: "[]" };
        expect(enrich(item)).toEqual({ ...item, isActive: false });
    });

    test("an item named in the query is active", () => {
        const item = { id: 1, type: "filter" };
        expect(enrich(item, [{ searchItemId: 1 }]).isActive).toBe(true);
    });

    test("the raw item is not mutated", () => {
        const item = { id: 1, type: "field", fieldName: "foo" };
        enrich(item, [{ searchItemId: 1, autocompleteValue: { value: "a" } }]);
        expect(item).toEqual({ id: 1, type: "field", fieldName: "foo" });
    });

    test("an indexed query and a raw query agree", () => {
        const item = { id: 1, type: "field", fieldName: "foo" };
        const query = [
            { searchItemId: 1, autocompleteValue: { label: "A", value: 1 } },
            { searchItemId: 2, autocompleteValue: { label: "B", value: 2 } },
        ];
        expect(enrich(item, query)).toEqual(
            enrichSearchItem(
                /** @type {any} */ (item),
                indexQueryBySearchItem(/** @type {any} */ (query)),
                MOMENT,
                INTERVALS,
            ),
        );
    });

    test("a field collects its autocomplete values in query order", () => {
        const item = { id: 1, type: "field", fieldName: "foo" };
        const enriched = enrich(item, [
            { searchItemId: 1, autocompleteValue: { label: "A", value: 1 } },
            { searchItemId: 2, autocompleteValue: { label: "X", value: 9 } },
            { searchItemId: 1, autocompleteValue: { label: "B", value: 2 } },
        ]);
        expect(enriched.autocompleteValues).toEqual([
            { label: "A", value: 1 },
            { label: "B", value: 2 },
        ]);
    });

    test("a field_property collects them the same way", () => {
        const item = { id: 1, type: "field_property", fieldName: "props" };
        const enriched = enrich(item, [
            { searchItemId: 1, autocompleteValue: { label: "A", value: 1 } },
        ]);
        expect(enriched.autocompleteValues).toEqual([{ label: "A", value: 1 }]);
    });

    test("a properties field short-circuits: no options, no values -- but still isActive", () => {
        const item = { id: 1, type: "field", fieldType: "properties" };
        const enriched = enrich(item, [{ searchItemId: 1 }]);
        expect(enriched).toEqual({ ...item, isActive: true });
        expect(enriched.options).toBe(undefined);
        expect(enriched.autocompleteValues).toBe(undefined);
    });

    test("a properties field with nothing in the query is inactive", () => {
        const item = { id: 1, type: "field", fieldType: "properties" };
        expect(enrich(item, []).isActive).toBe(false);
    });

    test("a dateGroupBy mirrors the interval options and flags the chosen ones", () => {
        const item = { id: 1, type: "dateGroupBy", fieldName: "date_field" };
        const enriched = enrich(item, [
            { searchItemId: 1, intervalId: "month" },
            { searchItemId: 1, intervalId: "year" },
        ]);
        expect(enriched.options).toHaveLength(INTERVALS.length);
        const active = enriched.options
            .filter((/** @type {any} */ o) => o.isActive)
            .map((/** @type {any} */ o) => o.id);
        expect(active).toEqual(["year", "month"]);
        expect(enriched.options[0]).not.toBe(INTERVALS[0]);
    });

    test("a dateFilter with no optionsParams gets an empty option list", () => {
        const item = { id: 1, type: "dateFilter", fieldName: "date_field" };
        expect(enrich(item, [{ searchItemId: 1 }]).options).toEqual([]);
    });

    test("a dateFilter flags the selected periods", () => {
        const item = {
            id: 1,
            type: "dateFilter",
            fieldName: "date_field",
            optionsParams: {
                startYear: -2,
                endYear: 0,
                startMonth: -2,
                endMonth: 0,
                /** @type {any[]} */
                customOptions: [],
            },
        };
        const enriched = enrich(item, [{ searchItemId: 1, generatorId: "year" }]);
        const active = enriched.options
            .filter((/** @type {any} */ o) => o.isActive)
            .map((/** @type {any} */ o) => o.id);
        expect(active).toEqual(["year"]);
        expect(enriched.options.length).toBeGreaterThan(1);
    });

    test("an option list carries only what the menu renders", () => {
        const item = { id: 1, type: "dateGroupBy", fieldName: "date_field" };
        const [option] = enrich(item, []).options;
        expect(Object.keys(option).sort()).toEqual([
            "description",
            "groupNumber",
            "id",
            "isActive",
        ]);
    });

    for (const type of ["filter", "favorite", "groupBy"]) {
        test(`a ${type} gets isActive and nothing else added`, () => {
            const item = { id: 1, type, description: "D" };
            expect(enrich(item, [{ searchItemId: 1 }])).toEqual({
                ...item,
                isActive: true,
            });
        });
    }
});
