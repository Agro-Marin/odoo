// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { findDependencyCycle } from "@web/core/utils/dependency_graph";

describe.current.tags("headless");

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
        //   a
        //  / \
        // b   c
        //  \ /
        //   d
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
        const cycle = findDependencyCycle(graph);
        expect(cycle).not.toBe(null);
        // Cycle should contain both nodes and close the loop
        expect(cycle.length).toBeGreaterThan(2);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("three-node cycle", () => {
        const graph = new Map([
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["a"]],
        ]);
        const cycle = findDependencyCycle(graph);
        expect(cycle).not.toBe(null);
        // Must be a valid cycle: first === last
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
        // All three nodes in the cycle
        const nodes = new Set(cycle);
        expect(nodes.has("a")).toBe(true);
        expect(nodes.has("b")).toBe(true);
        expect(nodes.has("c")).toBe(true);
    });

    test("cycle in subgraph (not all nodes in cycle)", () => {
        // d → a → b → c → a (cycle), but d is not part of the cycle
        const graph = new Map([
            ["d", ["a"]],
            ["a", ["b"]],
            ["b", ["c"]],
            ["c", ["a"]],
        ]);
        const cycle = findDependencyCycle(graph);
        expect(cycle).not.toBe(null);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
        // d should NOT be in the cycle
        expect(cycle.includes("d")).toBe(false);
    });

    test("external dependencies (not in graph keys) are ignored", () => {
        // "external" is referenced but not a key in the graph
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
            // Disconnected component with cycle
            ["x", ["y"]],
            ["y", ["x"]],
        ]);
        const cycle = findDependencyCycle(graph);
        expect(cycle).not.toBe(null);
        expect(cycle[0]).toBe(cycle[cycle.length - 1]);
    });

    test("large acyclic graph does not stack overflow", () => {
        // Build a long chain: n0 → n1 → n2 → ... → n999
        const graph = new Map();
        for (let i = 0; i < 1000; i++) {
            graph.set(`n${i}`, [`n${i + 1}`]);
        }
        graph.set("n1000", []);
        expect(findDependencyCycle(graph)).toBe(null);
    });
});
