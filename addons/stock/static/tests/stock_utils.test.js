import { describe, expect, test } from "@odoo/hoot";
import { shapeSampleBars } from "@stock/picking_type_dashboard_graph/picking_type_dashboard_graph_field";
import { activeModelOfOriginalAction } from "@stock/stock_forecasted/stock_forecasted";
import { parseJsonValue, readJsonValue } from "@stock/utils/json_field";
import { isTerminalState, leafPackageName } from "@stock/utils/stock_state";

describe("json_field", () => {
    test("an empty or malformed value degrades to the declared fallback", () => {
        expect(parseJsonValue('{"a":1}', {})).toEqual({ a: 1 });
        expect(parseJsonValue("", { a: 1 })).toEqual({ a: 1 });
        expect(parseJsonValue(false, [])).toEqual([]);
        expect(parseJsonValue(undefined, null)).toBe(null);
        expect(parseJsonValue("{oops", { safe: true })).toEqual({ safe: true });
    });

    test("the parse is cached against the owner until the raw string changes", () => {
        const owner = {};
        const first = readJsonValue(owner, '{"a":1}', {});
        const again = readJsonValue(owner, '{"a":1}', {});
        expect(again).toBe(first);
        const changed = readJsonValue(owner, '{"a":2}', {});
        expect(changed).not.toBe(first);
        expect(changed).toEqual({ a: 2 });
    });

    test("two owners do not share a cache entry", () => {
        const a = {};
        const b = {};
        expect(readJsonValue(a, '{"x":1}', {})).not.toBe(
            readJsonValue(b, '{"x":1}', {}),
        );
    });
});

describe("stock_state", () => {
    test("terminal states", () => {
        expect(isTerminalState("done")).toBe(true);
        expect(isTerminalState("cancel")).toBe(true);
        expect(isTerminalState("assigned")).toBe(false);
        expect(isTerminalState(false)).toBe(false);
        expect(isTerminalState(undefined)).toBe(false);
    });

    test("leaf package name", () => {
        expect(leafPackageName("PARENT > CHILD")).toBe("CHILD");
        expect(leafPackageName("A > B > C")).toBe("C");
        expect(leafPackageName("PACK0001")).toBe("PACK0001");
        expect(leafPackageName(false)).toBe(false);
        expect(leafPackageName(undefined)).toBe(undefined);
    });
});

describe("activeModelOfOriginalAction", () => {
    test("reads a structured context", () => {
        expect(
            activeModelOfOriginalAction(
                JSON.stringify({ context: { active_model: "product.product" } }),
            ),
        ).toBe("product.product");
    });

    test("reads a Python context expression, which is why this exists", () => {
        expect(
            activeModelOfOriginalAction(
                JSON.stringify({
                    context: "{'active_id': id, 'active_model': 'product.template'}",
                }),
            ),
        ).toBe("product.template");
    });

    test("returns undefined rather than throwing on anything unreadable", () => {
        expect(activeModelOfOriginalAction(undefined)).toBe(undefined);
        expect(activeModelOfOriginalAction("not json")).toBe(undefined);
        expect(activeModelOfOriginalAction(JSON.stringify({}))).toBe(undefined);
        expect(
            activeModelOfOriginalAction(JSON.stringify({ context: "{'a': 1}" })),
        ).toBe(undefined);
    });
});

describe("shapeSampleBars", () => {
    test("is deterministic for a given record", () => {
        const first = [{}, {}, {}, {}, {}, {}];
        const second = [{}, {}, {}, {}, {}, {}];
        shapeSampleBars(first, 42);
        shapeSampleBars(second, 42);
        expect(first.map((v) => v.value)).toEqual(second.map((v) => v.value));
    });

    test("differs between records and stays in the drawable range", () => {
        const a = [{}, {}, {}, {}, {}, {}];
        const b = [{}, {}, {}, {}, {}, {}];
        shapeSampleBars(a, 1);
        shapeSampleBars(b, 2);
        expect(a.map((v) => v.value)).not.toEqual(b.map((v) => v.value));
        for (const value of [...a, ...b]) {
            expect(value.value).toBeGreaterThan(0);
            expect(value.value).toBeLessThan(10);
        }
    });
});
