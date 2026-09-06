// @ts-check
import { describe, expect, test } from "@odoo/hoot";
import { aggregateSubdivisions } from "@web/views/pivot/pivot_aggregation";
import { findGroup } from "@web/views/pivot/pivot_group_tree";

describe.current.tags("headless");

function makeTree() {
    return { root: { labels: [], values: [] }, directSubTrees: new Map() };
}

function makeConfig(metaData = {}) {
    return {
        data: {
            rowGroupTree: makeTree(),
            colGroupTree: makeTree(),
            measurements: {},
            currencyIds: {},
            counts: {},
            groupDomains: {},
        },
        metaData: {
            activeMeasures: ["__count"],
            fields: {},
            measures: { __count: { type: "integer" } },
            sortedColumn: null,
            ...metaData,
        },
    };
}

const deps = {
    sortRows: () => expect.step("sortRows"),
    buildGroupLabels: (subGroup, groupBys) => groupBys.map((gb) => `${subGroup[gb]}!`),
    buildGroupValues: (subGroup, groupBys) => groupBys.map((gb) => subGroup[gb]),
    buildMeasurements: (subGroup) => ({ __count: subGroup.__count }),
};

const subdivisions = [
    {
        rowGroupBy: ["a"],
        colGroupBy: [],
        subGroups: [
            { a: 1, __count: 3, __domain: [["a", "=", 1]] },
            { a: 2, __count: 4 },
        ],
    },
    {
        rowGroupBy: [],
        colGroupBy: ["b"],
        subGroups: [{ b: "x", __count: 7, __domain: [["b", "=", "x"]] }],
    },
    {
        rowGroupBy: ["a"],
        colGroupBy: ["b"],
        subGroups: [{ a: 1, b: "x", __count: 3, __domain: [] }],
    },
];

test("row-only and column-only subgroups grow their tree, cells grow neither", () => {
    const config = makeConfig();
    aggregateSubdivisions({ rowValues: [], colValues: [] }, subdivisions, config, deps);
    const { data } = config;
    expect([...data.rowGroupTree.directSubTrees.keys()]).toEqual([1, 2]);
    expect(findGroup(data.rowGroupTree, [1]).root).toEqual({
        labels: ["1!"],
        values: [1],
    });
    expect([...data.colGroupTree.directSubTrees.keys()]).toEqual(["x"]);
    expect(Object.keys(data.measurements)).toEqual([
        "[[1],[]]",
        "[[2],[]]",
        '[[],["x"]]',
        '[[1],["x"]]',
    ]);
    expect(data.counts['[[1],["x"]]']).toBe(3);
    expect(data.measurements["[[2],[]]"]).toEqual({ __count: 4 });
    expect.verifySteps([]);
});

test("a subgroup with no domain is given the empty-set domain, not none", () => {
    const config = makeConfig();
    aggregateSubdivisions({ rowValues: [], colValues: [] }, subdivisions, config, deps);
    expect(config.data.groupDomains["[[1],[]]"]).toEqual([["a", "=", 1]]);
    expect(config.data.groupDomains["[[2],[]]"]).toEqual([[0, "=", 1]]);
});

test("a nested group prefixes its ancestors' values and labels", () => {
    const config = makeConfig();
    aggregateSubdivisions({ rowValues: [], colValues: [] }, subdivisions, config, deps);
    aggregateSubdivisions(
        { rowValues: [1], colValues: [] },
        [{ rowGroupBy: ["c"], colGroupBy: [], subGroups: [{ c: true, __count: 1 }] }],
        config,
        deps,
    );
    const nested = findGroup(config.data.rowGroupTree, [1, true]);
    expect(nested.root).toEqual({ labels: ["1!", "true!"], values: [1, true] });
    expect(config.data.counts["[[1,true],[]]"]).toBe(1);
});

test("a parent that is not in the tree aggregates nothing", () => {
    const config = makeConfig();
    aggregateSubdivisions(
        { rowValues: [99], colValues: [] },
        subdivisions,
        config,
        deps,
    );
    expect(config.data.measurements).toEqual({});
});

test("rows are sorted only when a column is sorted", () => {
    const config = makeConfig({
        sortedColumn: { groupId: [[], []], measure: "__count" },
    });
    aggregateSubdivisions({ rowValues: [], colValues: [] }, subdivisions, config, deps);
    expect.verifySteps(["sortRows"]);
});
