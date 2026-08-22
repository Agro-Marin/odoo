// @ts-check

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

        const { groups } = await runPostprocess(config, ["C", "A"]);

        expect(groups.map((g) => g.value)).toEqual(["C", "A", "B"]);
    });

    test("re-insertion is stable when a new group appears first", async () => {
        const config = makeConfig();
        await runPostprocess(config, ["A", "B"]);

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

    test("a re-inserted group resets its nested subgroups (2-level grouping)", async () => {
        const config = {
            ...makeConfig(),
            fields: {
                bar: { type: "char", name: "bar" },
                name: { type: "char", name: "name" },
            },
            groupBy: ["bar", "name"],
        };
        const makeNestedGroupData = (bar, subNames) => ({
            __count: subNames.length,
            __extra_domain: [["bar", "=", bar]],
            bar,
            __groups: {
                groups: subNames.map((name) => ({
                    __count: 1,
                    __extra_domain: [["name", "=", name]],
                    name,
                    __records: [{ id: subNames.indexOf(name) + 1, name }],
                })),
                length: subNames.length,
            },
        });
        const run = (names) =>
            postprocessReadGroup(
                config,
                {
                    groups: names.map((name) => makeNestedGroupData(name, ["x", "y"])),
                    length: names.length,
                },
                DEPS,
            );
        await run(["A", "B"]);

        const { groups } = await run(["B"]);

        expect(groups.map((g) => g.value)).toEqual(["A", "B"]);
        const sticky = groups[0];
        expect(sticky.count).toBe(0);
        expect(sticky.length).toBe(0);
        expect(sticky.groups).toEqual([]);
        expect(groups[1].groups.map((g) => g.value)).toEqual(["x", "y"]);
    });
});
