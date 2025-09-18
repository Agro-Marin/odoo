// @ts-check

/**
 * Pure unit tests for pivot model logic.
 *
 * Tests the core computation functions extracted from pivot_model.js into
 * pure utility modules. No OWL environment, ORM calls, or DOM fixtures needed.
 *
 * Modules under test:
 *  - views/pivot/pivot_group_tree.js  — tree data structure operations
 *  - views/pivot/pivot_value_utils.js — groupBy normalization, value sanitization
 *  - views/pivot/pivot_measurements.js — measure spec building
 */

import { describe, expect, test } from "@odoo/hoot";
import {
    addGroup,
    findGroup,
    getLeafCounts,
    getTreeHeight,
    hasData,
    pruneTree,
    sortTree,
} from "@web/views/pivot/pivot_group_tree";
import { getMeasureSpecs } from "@web/views/pivot/pivot_measurements";
import {
    getGroupBySpecs,
    getGroupDomain,
    getGroupValues,
} from "@web/views/pivot/pivot_value_utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal group tree node.
 * @param {Array} [values=[]] - group values (row or col)
 * @param {string[]} [labels=[]] - display labels
 * @returns {{ root: { values: Array, labels: string[] }, directSubTrees: Map }}
 */
function makeTree(values = [], labels = []) {
    return { root: { values, labels }, directSubTrees: new Map() };
}

/** Minimal pivot config for value utils. */
function makeConfig(fields = {}, extraData = {}) {
    return {
        metaData: { fields, activeMeasures: [] },
        data: { numbering: {}, groupDomains: {}, ...extraData },
    };
}

// ---------------------------------------------------------------------------
// addGroup
// ---------------------------------------------------------------------------

describe("addGroup — tree mutation", () => {
    test("adds a first-level group to an empty tree", () => {
        const tree = makeTree();

        addGroup(tree, ["Alice"], [1]);

        expect(tree.directSubTrees.has(1)).toBe(true);
        expect(tree.directSubTrees.get(1).root.labels).toEqual(["Alice"]);
        expect(tree.directSubTrees.get(1).root.values).toEqual([1]);
    });

    test("adds multiple first-level groups with distinct values", () => {
        const tree = makeTree();

        addGroup(tree, ["Alice"], [1]);
        addGroup(tree, ["Bob"], [2]);

        expect(tree.directSubTrees.size).toBe(2);
        expect(tree.directSubTrees.get(2).root.labels).toEqual(["Bob"]);
    });

    test("silently skips a duplicate value at the same level", () => {
        const tree = makeTree();
        addGroup(tree, ["Alice"], [1]);
        addGroup(tree, ["Alice Updated"], [1]); // same value

        // First registration wins
        expect(tree.directSubTrees.get(1).root.labels).toEqual(["Alice"]);
        expect(tree.directSubTrees.size).toBe(1);
    });

    test("adds a nested group two levels deep", () => {
        const tree = makeTree();
        addGroup(tree, ["Europe"], [1]);
        addGroup(tree, ["Europe", "Brussels"], [1, 10]);

        const europeTree = tree.directSubTrees.get(1);
        expect(europeTree.directSubTrees.has(10)).toBe(true);
        expect(europeTree.directSubTrees.get(10).root.labels).toEqual([
            "Europe",
            "Brussels",
        ]);
    });
});

// ---------------------------------------------------------------------------
// findGroup
// ---------------------------------------------------------------------------

describe("findGroup — tree lookup", () => {
    test("finds a first-level group by value", () => {
        const tree = makeTree();
        addGroup(tree, ["Alice"], [1]);

        const found = findGroup(tree, [1]);

        expect(found.root.labels).toEqual(["Alice"]);
    });

    test("finds a nested group by path of values", () => {
        const tree = makeTree();
        addGroup(tree, ["Europe"], [1]);
        addGroup(tree, ["Europe", "Brussels"], [1, 10]);

        const found = findGroup(tree, [1, 10]);

        expect(found.root.labels).toEqual(["Europe", "Brussels"]);
    });

    test("returns undefined for a missing value", () => {
        const tree = makeTree();

        expect(findGroup(tree, [99])).toBe(undefined);
    });

    test("returns the root tree when values is empty", () => {
        const tree = makeTree([], []);

        expect(findGroup(tree, [])).toBe(tree);
    });
});

// ---------------------------------------------------------------------------
// getTreeHeight
// ---------------------------------------------------------------------------

describe("getTreeHeight — depth computation", () => {
    test("single root with no children has height 1", () => {
        expect(getTreeHeight(makeTree())).toBe(1);
    });

    test("root with one level of children has height 2", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);

        expect(getTreeHeight(tree)).toBe(2);
    });

    test("two levels of children gives height 3", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["A", "B"], [1, 2]);

        expect(getTreeHeight(tree)).toBe(3);
    });

    test("height is the maximum depth across branches", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["B"], [2]);
        addGroup(tree, ["A", "C"], [1, 3]); // depth 2 under A

        // Max(2, 1) + 1 = 3
        expect(getTreeHeight(tree)).toBe(3);
    });
});

// ---------------------------------------------------------------------------
// getLeafCounts
// ---------------------------------------------------------------------------

describe("getLeafCounts — leaf node counting", () => {
    test("a node with no children has leaf count 1", () => {
        const leaf = makeTree([1], ["A"]);
        const counts = getLeafCounts(leaf);

        expect(counts[JSON.stringify([1])]).toBe(1);
    });

    test("root with two leaf children has leaf count 2", () => {
        const root = makeTree([], []);
        root.directSubTrees.set(1, makeTree([1], ["A"]));
        root.directSubTrees.set(2, makeTree([2], ["B"]));

        const counts = getLeafCounts(root);

        expect(counts[JSON.stringify([])]).toBe(2);
        expect(counts[JSON.stringify([1])]).toBe(1);
        expect(counts[JSON.stringify([2])]).toBe(1);
    });

    test("leaf counts accumulate correctly for a three-node path", () => {
        const root = makeTree([], []);
        const mid = makeTree([1], ["A"]);
        mid.directSubTrees.set(2, makeTree([1, 2], ["A", "B"]));
        root.directSubTrees.set(1, mid);

        const counts = getLeafCounts(root);

        // Only the deepest node [1,2] is a true leaf → all ancestors = 1
        expect(counts[JSON.stringify([])]).toBe(1);
        expect(counts[JSON.stringify([1])]).toBe(1);
        expect(counts[JSON.stringify([1, 2])]).toBe(1);
    });
});

// ---------------------------------------------------------------------------
// hasData
// ---------------------------------------------------------------------------

describe("hasData — table non-emptiness", () => {
    test("returns true when the total cell count is positive", () => {
        const data = { counts: { [JSON.stringify([[], []])]: 5 } };

        expect(hasData(data)).toBe(true);
    });

    test("returns false when the total cell count is zero", () => {
        const data = { counts: { [JSON.stringify([[], []])]: 0 } };

        expect(hasData(data)).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// pruneTree
// ---------------------------------------------------------------------------

describe("pruneTree — collapse to oldTree shape", () => {
    test("clears all children when oldTree is a leaf", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["B"], [2]);

        const oldTree = makeTree(); // no children

        pruneTree(tree, oldTree);

        expect(tree.directSubTrees.size).toBe(0);
    });

    test("preserves children that exist in oldTree", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["B"], [2]);

        const oldTree = makeTree();
        oldTree.directSubTrees.set(1, makeTree([1], ["A"])); // only "A" was expanded

        pruneTree(tree, oldTree);

        // "A" (key=1) still has its subtree; "B" (key=2) is now a leaf
        expect(tree.directSubTrees.has(1)).toBe(true);
        expect(tree.directSubTrees.get(2).directSubTrees.size).toBe(0);
    });

    test("recursively prunes nested subtrees to match oldTree depth", () => {
        // tree: root → A → B → C (depth 3)
        // oldTree: root → A (leaf, depth 1)
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["A", "B"], [1, 2]);
        addGroup(tree, ["A", "B", "C"], [1, 2, 3]);

        const oldTree = makeTree();
        const oldA = makeTree([1], ["A"]); // leaf (no children)
        oldTree.directSubTrees.set(1, oldA);

        pruneTree(tree, oldTree);

        // A should be pruned to a leaf (B and C gone)
        expect(tree.directSubTrees.get(1).directSubTrees.size).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// sortTree
// ---------------------------------------------------------------------------

describe("sortTree — key ordering", () => {
    test("sets sortedKeys in ascending order", () => {
        const tree = makeTree();
        addGroup(tree, ["B"], [2]);
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["C"], [3]);

        // sortFunction returns identity (numeric ascending)
        sortTree((_tree) => (key) => key, tree);

        expect(tree.sortedKeys).toEqual([1, 2, 3]);
    });

    test("sets sortedKeys in descending order with negated key", () => {
        const tree = makeTree();
        addGroup(tree, ["B"], [2]);
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["C"], [3]);

        sortTree((_tree) => (key) => -key, tree);

        expect(tree.sortedKeys).toEqual([3, 2, 1]);
    });

    test("recursively sorts nested subtrees", () => {
        const tree = makeTree();
        addGroup(tree, ["A"], [1]);
        addGroup(tree, ["A", "D"], [1, 4]);
        addGroup(tree, ["A", "C"], [1, 3]);

        sortTree((_tree) => (key) => key, tree);

        const aTree = tree.directSubTrees.get(1);
        expect(aTree.sortedKeys).toEqual([3, 4]); // ascending
    });
});

// ---------------------------------------------------------------------------
// getGroupValues — value sanitization
// ---------------------------------------------------------------------------

describe("getGroupValues — value extraction", () => {
    const fields = {
        partner_id: { type: "many2one" },
        date_field: { type: "date" },
        state: { type: "selection" },
    };

    test("sanitizes many2one array to its id (first element)", () => {
        const group = { partner_id: [1, "Alice"] };
        const result = getGroupValues(group, ["partner_id"], fields);

        expect(result).toEqual([1]);
    });

    test("keeps scalar value unchanged", () => {
        const group = { state: "draft" };
        const result = getGroupValues(group, ["state"], fields);

        expect(result).toEqual(["draft"]);
    });

    test("normalizes date field groupBy name to include interval", () => {
        // "date_field" without interval → normalize adds ":month"
        const group = { "date_field:month": "2024-01" };
        const result = getGroupValues(group, ["date_field"], fields);

        expect(result).toEqual(["2024-01"]);
    });

    test("handles multiple groupBys in order", () => {
        const group = { partner_id: [1, "Alice"], state: "done" };
        const result = getGroupValues(group, ["partner_id", "state"], fields);

        expect(result).toEqual([1, "done"]);
    });
});

// ---------------------------------------------------------------------------
// getGroupBySpecs — deduplication and normalization
// ---------------------------------------------------------------------------

describe("getGroupBySpecs — spec building", () => {
    const fields = {
        partner_id: { type: "many2one" },
        date_field: { type: "date" },
        sale_team_id: { type: "many2one" },
    };

    test("merges row and col groupBys in order, without duplicates", () => {
        const result = getGroupBySpecs(["partner_id"], ["sale_team_id"], fields);

        expect(result).toEqual(["partner_id", "sale_team_id"]);
    });

    test("normalizes date field without interval to add :month", () => {
        const result = getGroupBySpecs(["date_field"], [], fields);

        expect(result).toEqual(["date_field:month"]);
    });

    test("deduplicates when same normalized spec appears in both row and col", () => {
        const result = getGroupBySpecs(["partner_id"], ["partner_id"], fields);

        expect(result).toEqual(["partner_id"]);
    });

    test("preserves an explicit interval on a date field", () => {
        const result = getGroupBySpecs(["date_field:week"], [], fields);

        expect(result).toEqual(["date_field:week"]);
    });
});

// ---------------------------------------------------------------------------
// getGroupDomain — domain lookup from data
// ---------------------------------------------------------------------------

describe("getGroupDomain — domain retrieval", () => {
    test("returns the domain for a given row/col group pair", () => {
        const rowValues = [1];
        const colValues = [2];
        const key = JSON.stringify([rowValues, colValues]);
        const config = makeConfig({}, { groupDomains: { [key]: [["id", "=", 5]] } });

        const result = getGroupDomain(
            { rowValues, colValues },
            config,
        );

        expect(result).toEqual([["id", "=", 5]]);
    });

    test("returns undefined when group has no pre-computed domain", () => {
        const config = makeConfig({}, { groupDomains: {} });

        const result = getGroupDomain({ rowValues: [99], colValues: [] }, config);

        expect(result).toBe(undefined);
    });
});

// ---------------------------------------------------------------------------
// getMeasureSpecs — measure spec building
// ---------------------------------------------------------------------------

describe("getMeasureSpecs — aggregator normalization", () => {
    test("__count passes through unchanged", () => {
        const config = {
            metaData: { activeMeasures: ["__count"], fields: {} },
        };

        expect(getMeasureSpecs(config)).toEqual(["__count"]);
    });

    test("float field gets field:aggregator format", () => {
        const config = {
            metaData: {
                activeMeasures: ["amount"],
                fields: { amount: { type: "float", aggregator: "sum" } },
            },
        };

        expect(getMeasureSpecs(config)).toEqual(["amount:sum"]);
    });

    test("many2one field gets count_distinct aggregator", () => {
        const config = {
            metaData: {
                activeMeasures: ["partner_id"],
                fields: { partner_id: { type: "many2one" } },
            },
        };

        expect(getMeasureSpecs(config)).toEqual(["partner_id:count_distinct"]);
    });

    test("multiple measures combined in order", () => {
        const config = {
            metaData: {
                activeMeasures: ["__count", "amount"],
                fields: { amount: { type: "float", aggregator: "avg" } },
            },
        };

        expect(getMeasureSpecs(config)).toEqual(["__count", "amount:avg"]);
    });

    test("throws when float field has no aggregator defined", () => {
        const config = {
            metaData: {
                activeMeasures: ["amount"],
                fields: { amount: { type: "float" } }, // no aggregator
            },
        };

        expect(() => getMeasureSpecs(config)).toThrow();
    });
});
