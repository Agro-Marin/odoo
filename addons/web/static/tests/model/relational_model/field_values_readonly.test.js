// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { fromUnityToServerValues } from "@web/model/relational_model/field_values";

describe.current.tags("headless");

const FIELDS = {
    flag: { name: "flag", type: "boolean" },
    count: { name: "count", type: "integer" },
};

describe("fromUnityToServerValues readonly modifier", () => {
    test("a modifier evaluating to True strips the value", () => {
        const out = fromUnityToServerValues(
            { flag: true },
            FIELDS,
            { flag: { readonly: "True" } },
            { withReadonly: false, evalContext: {} },
        );
        expect(out).toEqual({});
    });

    test("a modifier evaluating to False keeps the value", () => {
        const out = fromUnityToServerValues(
            { flag: true },
            FIELDS,
            { flag: { readonly: "False" } },
            { withReadonly: false, evalContext: {} },
        );
        expect(out).toEqual({ flag: true });
    });

    test("a modifier evaluating to an empty list is Python-falsy (writable)", () => {
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "ids" } },
            { withReadonly: false, evalContext: { ids: [] } },
        );
        expect(out).toEqual({ count: 5 });
    });

    test("a non-empty list modifier is Python-truthy (readonly), stripped", () => {
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "ids" } },
            { withReadonly: false, evalContext: { ids: [1] } },
        );
        expect(out).toEqual({});
    });

    test("an unevaluable modifier stays writable (fail-open, unchanged)", () => {
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "missing_var == 1" } },
            { withReadonly: false, evalContext: {} },
        );
        expect(out).toEqual({ count: 5 });
    });

    test("withReadonly=true bypasses the readonly gate entirely", () => {
        const out = fromUnityToServerValues(
            { flag: true },
            FIELDS,
            { flag: { readonly: "True" } },
            { withReadonly: true, evalContext: {} },
        );
        expect(out).toEqual({ flag: true });
    });

    test("a modifier reads the record's eval context, parent included", () => {
        const evalContext = { state: "done", parent: { locked: true } };
        expect(
            fromUnityToServerValues(
                { count: 5 },
                FIELDS,
                { count: { readonly: "state != 'draft'" } },
                { withReadonly: false, evalContext },
            ),
        ).toEqual({});
        expect(
            fromUnityToServerValues(
                { flag: true },
                FIELDS,
                { flag: { readonly: "parent.locked" } },
                { withReadonly: false, evalContext },
            ),
        ).toEqual({});
        expect(
            fromUnityToServerValues(
                { flag: true },
                FIELDS,
                { flag: { readonly: "not parent.locked" } },
                { withReadonly: false, evalContext },
            ),
        ).toEqual({ flag: true });
    });
});
