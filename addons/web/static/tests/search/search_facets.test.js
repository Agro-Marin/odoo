// @ts-check

/**
 * Pure unit tests for search/search_facets.js.
 *
 * `buildFacets` is a free function over plain data — no OWL, no models, no
 * server calls — so it is exercised directly with hand-built query groups.
 */

import { describe, expect, test } from "@odoo/hoot";
import { buildFacets } from "@web/search/search_facets";
import { SPECIAL } from "@web/search/search_state";
import { FACET_ICONS } from "@web/search/utils/misc";

describe.current.tags("headless");

/**
 * Build the `buildFacets` parameters, with sensible empty defaults.
 * @param {Object} [overrides]
 * @returns {Object}
 */
function makeParams(overrides = {}) {
    return {
        groups: [],
        searchItems: {},
        getSearchItemDomain: () => null,
        getDateFilterDomain: () => "",
        orderByCount: false,
        globalGroupBy: [],
        defaultGroupBy: undefined,
        searchViewFields: {},
        viewType: "list",
        ...overrides,
    };
}

/** A single-item query group holding a group-by search item. */
function groupByGroup(searchItemId = 1) {
    return {
        groups: [{ id: 10, activeItems: [{ searchItemId }] }],
        searchItems: {
            [searchItemId]: { type: "groupBy", description: "Bar" },
        },
    };
}

describe("group-by facet icon", () => {
    test("plain group-by icon when the count sort is off", () => {
        const facets = buildFacets(makeParams(groupByGroup()));
        expect(facets).toHaveLength(1);
        expect(facets[0].icon).toBe(FACET_ICONS.groupBy);
    });

    test("ascending count-sort icon", () => {
        const facets = buildFacets(
            makeParams({ ...groupByGroup(), orderByCount: "Asc" }),
        );
        expect(facets[0].icon).toBe(FACET_ICONS.groupByAsc);
    });

    test("descending count-sort icon", () => {
        const facets = buildFacets(
            makeParams({ ...groupByGroup(), orderByCount: "Desc" }),
        );
        expect(facets[0].icon).toBe(FACET_ICONS.groupByDesc);
    });
});

describe("default group-by facet", () => {
    test("is added when nothing else groups", () => {
        const facets = buildFacets(
            makeParams({
                defaultGroupBy: ["bar"],
                searchViewFields: { bar: { string: "Bar" } },
            }),
        );
        expect(facets).toHaveLength(1);
        expect(facets[0].groupId).toBe(SPECIAL);
        expect(facets[0].values).toEqual(["Bar"]);
        expect(facets[0].icon).toBe(FACET_ICONS.groupBy);
    });

    test("carries the count-sort icon like a real group-by facet", () => {
        // `computeOrderBy` count-sorts a surviving `defaultGroupBy` and
        // `_checkOrderByCountStatus` keeps `orderByCount` alive for it, so the
        // facet — the only control that flips the sort — must show it.
        for (const [orderByCount, icon] of [
            ["Asc", FACET_ICONS.groupByAsc],
            ["Desc", FACET_ICONS.groupByDesc],
        ]) {
            const facets = buildFacets(
                makeParams({
                    orderByCount,
                    defaultGroupBy: ["bar"],
                    searchViewFields: { bar: { string: "Bar" } },
                }),
            );
            expect(facets[0].icon).toBe(icon);
        }
    });

    test("is not added when a group-by facet is already present", () => {
        const facets = buildFacets(
            makeParams({ ...groupByGroup(), defaultGroupBy: ["bar"] }),
        );
        expect(facets).toHaveLength(1);
        expect(facets[0].groupId).toBe(10);
    });

    test("is not added in kanban", () => {
        const facets = buildFacets(
            makeParams({ defaultGroupBy: ["bar"], viewType: "kanban" }),
        );
        expect(facets).toHaveLength(0);
    });
});

describe("date group-by facet", () => {
    /** A single-item query group holding a dateGroupBy search item. */
    function dateGroupByGroup(intervalIds) {
        return {
            groups: [{ id: 10, activeItems: [{ searchItemId: 1, intervalIds }] }],
            searchItems: {
                1: { id: 1, type: "dateGroupBy", description: "Date" },
            },
        };
    }

    test("describes a UI interval", () => {
        const facets = buildFacets(makeParams(dateGroupByGroup(["month"])));
        expect(facets[0].values).toEqual(["Date: Month"]);
    });

    test("describes a backend-only interval instead of dropping it", () => {
        // `hour` is a legal group-by interval — `getGroupBy` accepts it and a
        // `<filter context="{'group_by': 'x:hour'}">` puts it straight into the
        // query — it is only absent from the five the UI offers. Looking it up
        // in the UI table left the facet with NO values: an empty chip.
        const facets = buildFacets(makeParams(dateGroupByGroup(["hour"])));
        expect(facets[0].values).toEqual(["Date: Hour"]);
    });

    test("falls back to the raw id for an unknown interval", () => {
        const facets = buildFacets(makeParams(dateGroupByGroup(["fortnight"])));
        expect(facets[0].values).toEqual(["Date: fortnight"]);
    });

    test("the default group-by facet describes its interval too", () => {
        const facets = buildFacets(
            makeParams({
                defaultGroupBy: ["bar:hour"],
                searchViewFields: { bar: { string: "Bar" } },
            }),
        );
        expect(facets[0].values).toEqual(["Bar: Hour"]);
    });
});
