// @ts-check

/**
 * Pure unit tests for search/search_group_by.js — free functions over plain
 * data, exercised directly with hand-built query groups and search items.
 */

import { describe, expect, test } from "@odoo/hoot";
import { computeOrderBy, findGroupByGroupId } from "@web/search/search_group_by";

describe.current.tags("headless");

describe("findGroupByGroupId", () => {
    test("returns the groupId of the first group-by item", () => {
        const searchItems = {
            1: { type: "filter", groupId: 1 },
            2: { type: "groupBy", groupId: 7 },
            3: { type: "groupBy", groupId: 7 },
        };
        expect(findGroupByGroupId(searchItems)).toBe(7);
    });

    test("a dateGroupBy counts as a group-by", () => {
        expect(findGroupByGroupId({ 1: { type: "dateGroupBy", groupId: 4 } })).toBe(4);
    });

    test("returns undefined when the view has no group-by yet", () => {
        expect(findGroupByGroupId({ 1: { type: "filter", groupId: 1 } })).toBe(
            undefined,
        );
    });
});

describe("computeOrderBy", () => {
    /** A single-item query group holding a favorite. */
    function favoriteGroups() {
        return [{ id: 1, activeItems: [{ searchItemId: 1 }] }];
    }

    test("falls back to a COPY of globalOrderBy", () => {
        const globalOrderBy = [{ name: "foo", asc: true }];
        const result = computeOrderBy([], {}, [], false, globalOrderBy);
        expect(result).toEqual(globalOrderBy);
        expect(result).not.toBe(globalOrderBy);
    });

    test("copies a favorite's order terms instead of sharing them", () => {
        // The caller memoizes and freezes the result, but that freeze is
        // SHALLOW: handing out the favorite's own term objects let a consumer
        // editing a term corrupt the favorite for every later activation.
        const term = { name: "foo", asc: true };
        const searchItems = { 1: { type: "favorite", orderBy: [term] } };

        const result = computeOrderBy(favoriteGroups(), searchItems, [], false, []);

        expect(result).toEqual([{ name: "foo", asc: true }]);
        expect(result[0]).not.toBe(term);

        result[0].asc = false;
        expect(term.asc).toBe(true);
    });

    test("prepends the count term when a group-by is count-sorted", () => {
        const result = computeOrderBy([], {}, ["bar"], "Asc", []);
        expect(result).toEqual([{ name: "__count", asc: true }]);
    });
});
