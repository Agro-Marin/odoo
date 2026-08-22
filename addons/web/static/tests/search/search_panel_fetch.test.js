// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    createCategoryTree,
    createFilterTree,
} from "@web/search/search_panel/search_panel_fetch";

describe.current.tags("headless");

/**
 * @param {Record<string, any>[]} values
 * @returns {any}
 */
function buildGroups(values) {
    /** @type {Record<string, any>} */
    const filter = { groupBy: "category_id", values: new Map() };
    createFilterTree(filter, { values });
    return filter;
}

describe("createFilterTree group ordering", () => {
    test("orders by name when no sequence is supplied", () => {
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
        /** @type {Record<string, any>} */
        const category = {
            hierarchize: false,
            values: new Map(
                /** @type {any[]} */ ([[false, { id: false, childrenIds: [] }]]),
            ),
        };
        createCategoryTree(category, { error_msg: "boom" }, () => {});
        expect(category.errorMsg).toBe("boom");
        expect(category.rootIds).toEqual([false]);
    });

    test("a later success clears a previous error", () => {
        /** @type {Record<string, any>} */
        const category = {
            hierarchize: false,
            errorMsg: "boom",
            values: new Map(
                /** @type {any[]} */ ([[false, { id: false, childrenIds: [] }]]),
            ),
        };
        createCategoryTree(category, { values: [{ id: 1 }] }, () => {});
        expect("errorMsg" in category).toBe(false);
        expect(category.rootIds).toEqual([false, 1]);
    });
});

describe("createCategoryTree hierarchy", () => {
    /**
     * @param {Object[]} values
     * @param {Record<string, any>} [overrides]
     */
    function buildTree(values, overrides = {}) {
        /** @type {Record<string, any>} */
        const category = {
            hierarchize: true,
            values: new Map([
                [false, { id: false, display_name: "All", childrenIds: [] }],
            ]),
            ...overrides,
        };
        createCategoryTree(category, { parent_field: "parent_id", values }, () => {});
        return category;
    }

    function reachable(/** @type {any} */ category) {
        /** @type {Set<any>} */
        const seen = new Set();
        const walk = (/** @type {any} */ id) => {
            seen.add(id);
            for (const childId of category.values.get(id).childrenIds) {
                walk(childId);
            }
        };
        category.rootIds.forEach(walk);
        return seen;
    }

    test("children are attached to their parent and kept out of the roots", () => {
        const category = buildTree([
            { id: 1, parent_id: false },
            { id: 2, parent_id: 1 },
            { id: 3, parent_id: 1 },
        ]);
        expect(category.values.get(1).childrenIds).toEqual([2, 3]);
        expect(category.rootIds).toEqual([false, 1]);
        expect(category.values.get(2).parentId).toBe(1);
    });

    test("a grandchild hangs off its own parent, not the root", () => {
        const category = buildTree([
            { id: 1, parent_id: false },
            { id: 2, parent_id: 1 },
            { id: 3, parent_id: 2 },
        ]);
        expect(category.values.get(1).childrenIds).toEqual([2]);
        expect(category.values.get(2).childrenIds).toEqual([3]);
        expect(category.rootIds).toEqual([false, 1]);
    });

    test("a child declared before its parent still attaches", () => {
        const category = buildTree([
            { id: 2, parent_id: 1 },
            { id: 1, parent_id: false },
        ]);
        expect(category.values.get(1).childrenIds).toEqual([2]);
        expect(category.rootIds).toEqual([false, 1]);
    });

    test("a value whose parent is absent is still reachable", () => {
        const category = buildTree([
            { id: 1, parent_id: false },
            { id: 2, parent_id: 99 },
        ]);
        expect(reachable(category)).toEqual(new Set([false, 1, 2]));
        expect(category.rootIds).toEqual([false, 1, 2]);
    });

    test("a parent cycle does not make either value unreachable", () => {
        const category = buildTree([
            { id: 1, parent_id: 2 },
            { id: 2, parent_id: 1 },
        ]);
        expect(category.values.has(1)).toBe(true);
        expect(category.values.has(2)).toBe(true);
    });

    test("the All row survives a refetch with its children reset", () => {
        const category = buildTree([{ id: 1, parent_id: false }]);
        category.values.get(false).childrenIds.push(999);
        createCategoryTree(
            category,
            { parent_field: "parent_id", values: [{ id: 1, parent_id: false }] },
            () => {},
        );
        expect(category.values.get(false).display_name).toBe("All");
        expect(category.values.get(false).childrenIds).toEqual([]);
    });

    test("parentField is recorded only when the category hierarchizes", () => {
        expect(buildTree([{ id: 1 }]).parentField).toBe("parent_id");
        expect(buildTree([{ id: 1 }], { hierarchize: false }).parentField).toBe(
            undefined,
        );
    });

    test("a non-hierarchical payload makes every value a root", () => {
        /** @type {Record<string, any>} */
        const category = {
            hierarchize: false,
            values: new Map(
                /** @type {any[]} */ ([[false, { id: false, childrenIds: [] }]]),
            ),
        };
        createCategoryTree(
            category,
            { parent_field: false, values: [{ id: 1 }, { id: 2 }] },
            () => {},
        );
        expect(category.rootIds).toEqual([false, 1, 2]);
        expect(category.parentField).toBe(undefined);
    });

    test("ensureCategoryValue is handed every id the payload defines", () => {
        /** @type {any} */
        let seen;
        const category = {
            hierarchize: true,
            values: new Map(
                /** @type {any[]} */ ([[false, { id: false, childrenIds: [] }]]),
            ),
        };
        createCategoryTree(
            category,
            { parent_field: "parent_id", values: [{ id: 1 }, { id: 2 }] },
            (/** @type {any} */ _cat, /** @type {any} */ ids) => (seen = ids),
        );
        expect(seen).toEqual([false, 1, 2]);
    });
});
