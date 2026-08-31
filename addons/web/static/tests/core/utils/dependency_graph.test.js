// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    createWaveResolver,
    findDependencyCycle,
} from "@web/core/utils/dependency_graph";

describe.current.tags("headless");

/**
 * The cycle `graph` contains, asserted to exist.
 *
 * findDependencyCycle returns `string[] | null`; every caller below then indexes
 * into it. Saying "not null" with expect() does not narrow the type, which is
 * what produced 30 identical `possibly null` errors under the strict config.
 *
 * @param {Map<string, string[]>} graph
 * @returns {string[]}
 */
function expectCycle(graph) {
    const cycle = findDependencyCycle(graph);
    expect(cycle).not.toBe(null);
    return /** @type {string[]} */ (cycle);
}

describe("findDependencyCycle", () => {
    test("empty graph has no cycle", () => {
        expect(findDependencyCycle(new Map())).toBe(null);
    });

    test("single node with no deps", () => {
        const graph = new Map([["a", []]]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("linear chain has no cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("diamond graph has no cycle", () => {
        const graph = new Map([
            ["a", ["b", "c"]],
            ["b", ["d"]],
            ["c", ["d"]],
            ["d", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("self-loop detected", () => {
        const graph = new Map([["a", ["a"]]]);
        const cycle = findDependencyCycle(graph);
        expect(cycle).toEqual(["a", "a"]);
    });

    test("simple two-node cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["a"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle.length).toBeGreaterThan(2);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("three-node cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["a"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
        const nodes = new Set(cycle);
        expect(nodes.has("a")).toBe(true);
        expect(nodes.has("b")).toBe(true);
        expect(nodes.has("c")).toBe(true);
    });

    test("cycle in subgraph (not all nodes in cycle)", () => {
        const graph = new Map([
            ["d", ["a"]],
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["a"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
        expect(cycle.includes("d")).toBe(false);
    });

    test("external dependencies (not in graph keys) are ignored", () => {
        const graph = new Map([
            ["a", ["external", "b"]],
            ["b", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("disconnected components — cycle in second component", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", []],
            ["x", ["y"]],
            ["y", ["x"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("large acyclic graph does not stack overflow", () => {
        const graph = new Map();
        for (let i = 0; i < 1000; i++) {
            graph.set(`n${i}`, [`n${i + 1}`]);
        }
        graph.set("n1000", []);
        expect(findDependencyCycle(graph)).toBe(null);
    });
});

describe("createWaveResolver", () => {
    test("untrack then re-track re-imposes the dependency", () => {
        const r = createWaveResolver({ isLoaded: () => false });
        r.track("b", ["a"]);
        expect(r.pendingOf("b")).toBe(1);
        expect(r.hasReady()).toBe(false);

        r.untrack("b");
        expect(r.pendingOf("b")).toBe(undefined);

        r.track("b", ["a"]);
        expect(r.pendingOf("b")).toBe(1);
        expect(r.hasReady()).toBe(false);

        r.propagate("a");
        expect(r.pendingOf("b")).toBe(0);
        expect(r.shift()).toBe("b");
        expect(r.hasReady()).toBe(false);
    });

    test("untrack removes the entry from every dependents set", () => {
        const r = createWaveResolver({ isLoaded: () => false });
        r.track("b", ["a"]);
        r.untrack("b");
        r.propagate("a");
        expect(r.hasReady()).toBe(false);
        r.track("c", ["a"]);
        r.propagate("a");
        expect(r.shift()).toBe("c");
    });
});

/* --- merged from tests/core/dependency_graph.test.js: one module, one suite --- */
describe("findDependencyCycle", () => {
    test("returns null for empty graph", () => {
        const graph = new Map();
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("returns null for single node with no deps", () => {
        const graph = new Map([["a", []]]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("returns null for acyclic graph", () => {
        const graph = new Map([
            ["a", ["b", "c"]],
            ["b", ["c"]],
            ["c", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("detects self-loop", () => {
        const graph = new Map([["a", ["a"]]]);
        const cycle = findDependencyCycle(graph);
        expect(cycle).toEqual(["a", "a"]);
    });

    test("detects two-node cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["a"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle.length).toBe(3);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("detects three-node cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["a"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle.length).toBe(4);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("ignores external dependencies not in graph", () => {
        const graph = new Map([
            ["a", ["b", "external"]],
            ["b", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("detects cycle in subgraph (not all nodes involved)", () => {
        const graph = new Map([
            ["a", []],
            ["b", ["c"]],
            ["c", ["d"]],
            ["d", ["b"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle).not.toInclude("a");
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("works with diamond dependency (no cycle)", () => {
        const graph = new Map([
            ["a", ["b", "c"]],
            ["b", ["d"]],
            ["c", ["d"]],
            ["d", []],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });

    test("works with complex graph containing one cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["d", "e"]],
            ["d", []],
            ["e", ["f"]],
            ["f", ["c"]],
        ]);
        const cycle = expectCycle(graph);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
        for (const node of cycle) {
            expect(["c", "e", "f"]).toInclude(node);
        }
    });

    test("handles nodes with undefined deps (treated as empty)", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", undefined],
        ]);
        expect(findDependencyCycle(graph)).toBe(null);
    });
});
