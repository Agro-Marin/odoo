// @ts-check

/**
 * Pure unit tests for search/search_panel/search_panel_fetch.js — the
 * server-result → section-tree builders.
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    createCategoryTree,
    createFilterTree,
} from "@web/search/search_panel/search_panel_fetch";

describe.current.tags("headless");

/** Build a grouped filter section and feed it a server payload. */
function buildGroups(values) {
    const filter = { groupBy: "category_id", values: new Map() };
    createFilterTree(filter, { values });
    return filter;
}

describe("createFilterTree group ordering", () => {
    test("orders by name when no sequence is supplied", () => {
        // The live server payload: `search_panel_select_multi_range` emits
        // group_id / group_name and nothing else.
        const filter = buildGroups([
            { id: 1, group_id: 10, group_name: "Zeta" },
            { id: 2, group_id: 20, group_name: "Alpha" },
            { id: 3, group_id: 30, group_name: "Mid" },
        ]);
        expect(filter.sortedGroupIds).toEqual([20, 30, 10]);
    });

    test("a sequence on every group wins over the name", () => {
        const filter = buildGroups([
            { id: 1, group_id: 10, group_name: "Alpha", group_sequence: 3 },
            { id: 2, group_id: 20, group_name: "Zeta", group_sequence: 1 },
        ]);
        expect(filter.sortedGroupIds).toEqual([20, 10]);
    });

    test("sequenced groups come first, unsequenced fall back to name", () => {
        // A single `sequence || name` key made every unsequenced group compare
        // equal to every sequenced one, silently dropping the ordering.
        const filter = buildGroups([
            { id: 1, group_id: 10, group_name: "Zeta", group_sequence: 5 },
            { id: 2, group_id: 20, group_name: "Alpha" },
            { id: 3, group_id: 30, group_name: "Beta", group_sequence: 1 },
        ]);
        expect(filter.sortedGroupIds).toEqual([30, 10, 20]);
    });

    test("the falsy 'not set' group is excluded (rendered separately)", () => {
        const filter = buildGroups([
            { id: 1, group_id: false, group_name: false },
            { id: 2, group_id: 20, group_name: "Alpha" },
        ]);
        expect(filter.sortedGroupIds).toEqual([20]);
        expect(filter.groups.has(false)).toBe(true);
    });

    test("checked state survives a refetch", () => {
        const filter = buildGroups([{ id: 1, group_id: 10, group_name: "Alpha" }]);
        filter.values.get(1).checked = true;
        createFilterTree(filter, {
            values: [{ id: 1, group_id: 10, group_name: "Alpha" }],
        });
        expect(filter.values.get(1).checked).toBe(true);
    });
});

describe("createCategoryTree", () => {
    test("an error payload is stamped and clears the values", () => {
        const category = {
            hierarchize: false,
            values: new Map([[false, { id: false, childrenIds: [] }]]),
        };
        createCategoryTree(category, { error_msg: "boom" }, () => {});
        expect(category.errorMsg).toBe("boom");
        expect(category.rootIds).toEqual([false]);
    });

    test("a later success clears a previous error", () => {
        const category = {
            hierarchize: false,
            errorMsg: "boom",
            values: new Map([[false, { id: false, childrenIds: [] }]]),
        };
        createCategoryTree(category, { values: [{ id: 1 }] }, () => {});
        expect("errorMsg" in category).toBe(false);
        expect(category.rootIds).toEqual([false, 1]);
    });
});
