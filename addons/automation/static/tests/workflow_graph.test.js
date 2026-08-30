import { describe, expect, test } from "@odoo/hoot";
import {
    canConnect,
    conditionLabel,
    linkClasses,
    nodeClasses,
    shortName,
} from "@automation/workflow_graph";

const EDGES = [
    { id: 1, source: 10, target: 11, condition: "on_success" },
    { id: 2, source: 11, target: 12, condition: "on_error" },
];

describe("workflow canvas connection guard", () => {
    test("a fresh pair may be connected", () => {
        expect(canConnect(EDGES, 10, 12)).toBe(true);
    });

    test("a pair already connected may not be connected again", () => {
        expect(canConnect(EDGES, 10, 11)).toBe(false);
    });

    test("the reverse of an existing edge is still offered", () => {
        expect(canConnect(EDGES, 11, 10)).toBe(true);
    });

    test("a step may not be connected to itself", () => {
        expect(canConnect(EDGES, 10, 10)).toBe(false);
    });

    test("a drag that landed on nothing is refused", () => {
        expect(canConnect(EDGES, 10, undefined)).toBe(false);
        expect(canConnect(EDGES, null, 12)).toBe(false);
    });
});

describe("workflow canvas styling hooks", () => {
    test("a node with no run carries only the base class", () => {
        expect(nodeClasses({ id: 1 })).toBe("o_workflow_canvas_node");
    });

    test("a typed step is marked as one, a plain action is not", () => {
        for (const type of ["wait", "approval", "subflow"]) {
            expect(nodeClasses({ id: 1, node_type: type })).toInclude(
                `o_workflow_canvas_type_${type}`,
            );
        }
        expect(nodeClasses({ id: 1, node_type: "action" })).toBe(
            "o_workflow_canvas_node",
        );
    });

    test("a node in a run carries its state", () => {
        for (const state of [
            "waiting",
            "ready",
            "paused",
            "in_progress",
            "done",
            "error",
            "cancel",
        ]) {
            expect(nodeClasses({ id: 1, runtime_state: state })).toInclude(
                `o_workflow_canvas_run_${state}`,
            );
        }
    });

    test("a link carries its condition", () => {
        for (const condition of ["on_success", "on_error", "always", "expression"]) {
            expect(linkClasses({ condition })).toInclude(
                `o_workflow_canvas_${condition}`,
            );
            expect(linkClasses({ condition })).toInclude("o_workflow_canvas_link");
        }
    });

    test("every condition has its own label", () => {
        const conditions = ["on_success", "on_error", "always", "expression"];
        const labels = conditions.map((condition) => String(conditionLabel(condition)));

        for (const label of labels) {
            expect(label.length).toBeGreaterThan(0);
        }
        expect(new Set(labels).size).toBe(conditions.length);
    });

    test("a long step name is shortened, a short one is left alone", () => {
        expect(shortName("Send the email")).toBe("Send the email");
        expect(shortName("Send the email to everyone who asked").length).toBe(24);
        expect(shortName("")).toBe("");
        expect(shortName(undefined)).toBe("");
    });
});
