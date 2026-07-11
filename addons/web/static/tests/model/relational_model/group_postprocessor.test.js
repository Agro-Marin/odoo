// @ts-check

/**
 * Unit tests for the sticky-empty pass of ``postprocessReadGroup``: when the
 * same query re-runs and a group drops out of the response (records moved
 * out via kanban drag), it is re-inserted as an empty column. Insertion must
 * be positioned against the MERGED array — the old group's index is stale as
 * soon as the response comes back with fewer/reordered groups or one group
 * has already been re-inserted.
 */

import { describe, expect, test } from "@odoo/hoot";
import { postprocessReadGroup } from "@web/model/relational_model/group_postprocessor";

function makeConfig() {
    return {
        resModel: "task",
        fields: { name: { type: "char", name: "name" } },
        activeFields: {},
        fieldsToAggregate: [],
        domain: [],
        groupBy: ["name"],
        offset: 0,
        limit: 80,
        orderBy: [],
        groups: {},
    };
}

const DEPS = {
    getPropertyDefinition: async () => {},
    groupByInfo: {},
    initialLimit: 40,
    initialGroupsLimit: 10,
    defaultGroupLimit: 10,
};

function makeGroupData(name, count = 1) {
    return {
        __count: count,
        __extra_domain: [["name", "=", name]],
        name,
    };
}

async function runPostprocess(config, names) {
    const response = {
        groups: names.map((name) => makeGroupData(name)),
        length: names.length,
    };
    return postprocessReadGroup(config, response, DEPS);
}

describe("sticky-empty group re-insertion", () => {
    test("dropped groups are re-inserted in order on an identical reload", async () => {
        const config = makeConfig();
        await runPostprocess(config, ["A", "B", "C", "D"]);

        const { groups } = await runPostprocess(config, ["D"]);

        expect(groups.map((g) => g.value)).toEqual(["A", "B", "C", "D"]);
        const emptied = groups.filter((g) => g.value !== "D");
        for (const group of emptied) {
            expect(group.count).toBe(0);
            expect(group.records).toEqual([]);
        }
    });

    test("re-insertion follows the merged array when survivors are reordered", async () => {
        const config = makeConfig();
        await runPostprocess(config, ["A", "B", "C"]);

        // The response reorders the survivors: the dropped group (B) must be
        // re-inserted after its previous surviving neighbor (A) in the NEW
        // order — index-based splicing produced [C, B, A].
        const { groups } = await runPostprocess(config, ["C", "A"]);

        expect(groups.map((g) => g.value)).toEqual(["C", "A", "B"]);
    });

    test("re-insertion is stable when a new group appears first", async () => {
        const config = makeConfig();
        await runPostprocess(config, ["A", "B"]);

        // B dropped, E is new: B belongs after A, not between E and A.
        const { groups } = await runPostprocess(config, ["E", "A"]);

        expect(groups.map((g) => g.value)).toEqual(["E", "A", "B"]);
    });

    test("a changed query starts clean (no sticky re-insertion)", async () => {
        const config = makeConfig();
        await runPostprocess(config, ["A", "B"]);

        config.domain = [["name", "!=", false]];
        const { groups } = await runPostprocess(config, ["B"]);

        expect(groups.map((g) => g.value)).toEqual(["B"]);
    });
});
