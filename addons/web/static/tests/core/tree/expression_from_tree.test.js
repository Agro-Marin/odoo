// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    complexCondition,
    condition,
    connector,
    expression,
} from "@web/core/tree/condition_tree";
import { expressionFromTree } from "@web/core/tree/expression_from_tree";

test("expressionFromTree", () => {
    const options = {
        getFieldDef: (name) => {
            if (["foo", "bar"].includes(name)) {
                return { type: "any" };
            }
            if (["foo_ids", "bar_ids"].includes(name)) {
                return { type: "many2many" };
            }
            return null;
        },
    };
    const toTest = [
        {
            expressionTree: condition("foo", "=", false),
            result: `not foo`,
        },
        {
            expressionTree: condition("foo", "=", false, true),
            result: `foo`,
        },
        {
            expressionTree: condition("foo", "!=", false),
            result: `foo`,
        },
        {
            expressionTree: condition("foo", "!=", false, true),
            result: `not foo`,
        },
        {
            expressionTree: condition("y", "=", false),
            result: `not "y"`,
        },
        {
            expressionTree: condition("foo", "between", [1, 3]),
            result: `foo >= 1 and foo <= 3`,
        },
        {
            expressionTree: condition("foo", "between", [1, expression("uid")], true),
            result: `not ( foo >= 1 and foo <= uid )`,
        },
        {
            expressionTree: complexCondition("uid"),
            result: `uid`,
        },
        {
            expressionTree: condition("foo_ids", "in", []),
            result: `set(foo_ids).intersection([])`,
        },
        {
            expressionTree: condition("foo_ids", "in", [1]),
            result: `set(foo_ids).intersection([1])`,
        },
        {
            expressionTree: condition("foo_ids", "in", 1),
            result: `set(foo_ids).intersection([1])`,
        },
        {
            expressionTree: condition("foo", "in", []),
            result: `foo in []`,
        },
        {
            expressionTree: condition(expression("expr"), "in", []),
            result: `expr in []`,
        },
        {
            expressionTree: condition("foo", "in", [1]),
            result: `foo in [1]`,
        },
        {
            expressionTree: condition("foo", "in", 1),
            result: `foo in [1]`,
        },
        {
            expressionTree: condition("foo", "in", expression("expr")),
            result: `foo in expr`,
        },
        {
            expressionTree: condition("foo_ids", "in", expression("expr")),
            result: `set(foo_ids).intersection(expr)`,
        },
        {
            expressionTree: condition("y", "in", []),
            result: `"y" in []`,
        },
        {
            expressionTree: condition("y", "in", [1]),
            result: `"y" in [1]`,
        },
        {
            expressionTree: condition("y", "in", 1),
            result: `"y" in [1]`,
        },
        {
            expressionTree: condition("foo_ids", "not in", []),
            result: `not set(foo_ids).intersection([])`,
        },
        {
            expressionTree: condition("foo_ids", "not in", [1]),
            result: `not set(foo_ids).intersection([1])`,
        },
        {
            expressionTree: condition("foo_ids", "not in", 1),
            result: `not set(foo_ids).intersection([1])`,
        },
        {
            expressionTree: condition("foo", "not in", []),
            result: `foo not in []`,
        },
        {
            expressionTree: condition("foo", "not in", [1]),
            result: `foo not in [1]`,
        },
        {
            expressionTree: condition("foo", "not in", 1),
            result: `foo not in [1]`,
        },
        {
            expressionTree: condition("y", "not in", []),
            result: `"y" not in []`,
        },
        {
            expressionTree: condition("y", "not in", [1]),
            result: `"y" not in [1]`,
        },
        {
            expressionTree: condition("y", "not in", 1),
            result: `"y" not in [1]`,
        },
    ];
    for (const { expressionTree, result, extraOptions } of toTest) {
        const o = { ...options, ...extraOptions };
        expect(expressionFromTree(expressionTree, o)).toBe(result);
    }
});

test("expressionFromTree: constant condition leaves", () => {
    expect(expressionFromTree(condition(1, "=", 1))).toBe("True");
    expect(expressionFromTree(condition(0, "=", 1))).toBe("False");
    // A negated TRUE leaf normalizes to (1, "!=", 1), which has no expression
    // representation: it must THROW (never return an Error object that could
    // be persisted as the literal text "Error: Invalid condition").
    expect(() => expressionFromTree(condition(1, "=", 1, true))).toThrow(
        /Invalid condition/,
    );
    expect(() => expressionFromTree(condition(1, "!=", 1))).toThrow(
        /Invalid condition/,
    );
    expect(() => expressionFromTree(condition(0, "=", 2))).toThrow(/Invalid condition/);
});

test("expressionFromTree: complex conditions are parenthesized when needed", () => {
    const options = {
        getFieldDef: (name) => (name === "foo" ? { type: "integer" } : null),
    };
    // a bare `or`/ternary inside a connector would regroup on re-parse
    expect(
        expressionFromTree(
            connector("&", [condition("foo", "=", 1), complexCondition("a or b")]),
            options,
        ),
    ).toBe("foo == 1 and ( a or b )");
    expect(
        expressionFromTree(
            connector("&", [
                condition("foo", "=", 1),
                complexCondition("x if y else z"),
            ]),
            options,
        ),
    ).toBe("foo == 1 and ( x if y else z )");
    // tighter-binding roots stay bare
    expect(
        expressionFromTree(
            connector("&", [
                condition("foo", "=", 1),
                complexCondition(`context.get("k")`),
            ]),
            options,
        ),
    ).toBe(`foo == 1 and context.get("k")`);
    expect(
        expressionFromTree(
            connector("&", [condition("foo", "=", 1), complexCondition("not a")]),
            options,
        ),
    ).toBe("foo == 1 and not a");
    // at the root, no parentheses
    expect(expressionFromTree(complexCondition("a or b"), options)).toBe("a or b");
});
