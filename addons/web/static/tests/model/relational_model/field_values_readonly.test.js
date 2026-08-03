// @ts-check

/**
 * ``fromUnityToServerValues`` strips readonly fields when ``withReadonly`` is
 * false (the write/save path). It must decide "readonly" with the SAME rule the
 * UI used to gate the input — ``record._isReadonly`` ->
 * ``isFieldReadonly`` -> ``evaluateBooleanExpr`` (Python-boolean semantics) —
 * so what the user could edit is exactly what is sent. The former
 * ``evaluateExpr(...)`` + JS ``if (...)`` diverged on containers: an empty list
 * is JS-truthy but ``bool([])`` is False, so a writable field whose readonly
 * modifier evaluated to ``[]`` was wrongly stripped.
 */

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
            { withReadonly: false, context: {} },
        );
        expect(out).toEqual({});
    });

    test("a modifier evaluating to False keeps the value", () => {
        const out = fromUnityToServerValues(
            { flag: true },
            FIELDS,
            { flag: { readonly: "False" } },
            { withReadonly: false, context: {} },
        );
        expect(out).toEqual({ flag: true });
    });

    test("a modifier evaluating to an empty list is Python-falsy (writable)", () => {
        // Regression: evaluateExpr + JS `if ([])` treated this readonly and
        // stripped `count`; evaluateBooleanExpr matches the server (bool([]) is
        // False), so the field stays writable and is sent.
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "ids" } },
            { withReadonly: false, context: { ids: [] } },
        );
        expect(out).toEqual({ count: 5 });
    });

    test("a non-empty list modifier is Python-truthy (readonly), stripped", () => {
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "ids" } },
            { withReadonly: false, context: { ids: [1] } },
        );
        expect(out).toEqual({});
    });

    test("an unevaluable modifier stays writable (fail-open, unchanged)", () => {
        const out = fromUnityToServerValues(
            { count: 5 },
            FIELDS,
            { count: { readonly: "missing_var == 1" } },
            { withReadonly: false, context: {} },
        );
        expect(out).toEqual({ count: 5 });
    });

    test("withReadonly=true bypasses the readonly gate entirely", () => {
        const out = fromUnityToServerValues(
            { flag: true },
            FIELDS,
            { flag: { readonly: "True" } },
            { withReadonly: true, context: {} },
        );
        expect(out).toEqual({ flag: true });
    });
});
