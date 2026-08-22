// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Domain } from "@web/core/domain";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { expressionFromTree } from "@web/core/tree/expression_from_tree";
import { treeFromExpression } from "@web/core/tree/tree_from_expression";
import { introduceVirtualOperators } from "@web/core/tree/virtual_operators";

describe.current.tags("headless");

const FIELD_TYPES = {
    foo: "char",
    bar: "char",
    integer: "integer",
    other_integer: "integer",
    boolean_field: "boolean",
    foo_ids: "many2many",
    date_field: "date",
    datetime_field: "datetime",
};

const options = {
    getFieldDef: (name) => (FIELD_TYPES[name] ? { type: FIELD_TYPES[name] } : null),
    generateSmartDates: false,
};

const VARIABLE_DOMAIN = {
    foo: ["a", "b", ""],
    bar: ["a", "b", ""],
    integer: [0, 1, 5],
    boolean_field: [true, false],
};

function contextsFor(expression) {
    const names = Object.keys(VARIABLE_DOMAIN).filter((name) =>
        new RegExp(`\\b${name}\\b`).test(expression),
    );
    let contexts = [{}];
    for (const name of names) {
        contexts = contexts.flatMap((ctx) =>
            VARIABLE_DOMAIN[name].map((value) => ({ ...ctx, [name]: value })),
        );
    }
    return contexts;
}

const ATOMS = [
    `foo == "a"`,
    `foo != "a"`,
    `bar == "b"`,
    `integer > 1`,
    `integer <= 1`,
    `boolean_field`,
    `not boolean_field`,
    `not (foo == "a")`,
    `foo in ["a", "b"]`,
];

function* generateExpressions() {
    yield* ATOMS;
    for (const a of ATOMS) {
        yield `not (${a})`;
        for (const b of ATOMS) {
            yield `${a} and ${b}`;
            yield `${a} or ${b}`;
            yield `not (${a} and ${b})`;
            yield `not (${a} or ${b})`;
            for (const c of ATOMS) {
                yield `(${a} and ${b}) or (not (${a}) and ${c})`;
                yield `(${b} and ${a}) or (not (${a}) and ${c})`;
                yield `(${a} and not (${b})) or (${b} and ${c})`;
                yield `${b} if ${a} else ${c}`;
            }
        }
    }
}

test("expression -> tree -> expression preserves boolean meaning", () => {
    let checked = 0;
    let skipped = 0;
    const mismatches = [];
    for (const expression of generateExpressions()) {
        let roundTripped;
        try {
            roundTripped = expressionFromTree(
                treeFromExpression(expression, options),
                options,
            );
        } catch {
            skipped++;
            continue;
        }
        for (const context of contextsFor(expression)) {
            const before = evaluateBooleanExpr(expression, context);
            const after = evaluateBooleanExpr(roundTripped, context);
            checked++;
            if (before !== after && mismatches.length < 10) {
                mismatches.push(
                    `${expression}\n    -> ${roundTripped}\n    ctx=${JSON.stringify(context)} ${before} != ${after}`,
                );
            }
        }
    }
    expect(mismatches).toEqual([], {
        message: `${mismatches.length} semantic mismatches:\n  ${mismatches.join("\n  ")}`,
    });
    expect(checked).toBeGreaterThan(10000);
    expect(skipped).toBe(0, { message: "no generated expression should be rejected" });
});

const RECORDS = [
    // prettier-ignore
    { foo: "a", bar: "b", integer: 0, boolean_field: true, foo_ids: [],
      date_field: "2024-01-01", datetime_field: "2024-01-01 08:00:00" },
    // prettier-ignore
    { foo: "b", bar: "b", integer: 1, boolean_field: false, foo_ids: [1],
      date_field: "2024-06-15", datetime_field: "2024-06-15 12:30:00" },
    // prettier-ignore
    { foo: "", bar: "", integer: 5, boolean_field: false, foo_ids: [1, 2],
      date_field: "2025-03-20", datetime_field: "2025-03-20 23:59:59" },
    // prettier-ignore
    { foo: "a", bar: "", integer: 2, boolean_field: true, foo_ids: [2, 3],
      date_field: false, datetime_field: false },
    // prettier-ignore
    { foo: false, bar: false, integer: false, boolean_field: false, foo_ids: [],
      date_field: false, datetime_field: false },
];

const DOMAINS = [
    `[]`,
    `[("foo", "=", "a")]`,
    `[("foo", "!=", False)]`,
    `["!", ("foo", "=", "a")]`,
    `[("integer", ">", 1)]`,
    `["&", ("integer", ">=", 1), ("integer", "<=", 3)]`,
    `["|", ("foo", "=", "a"), ("bar", "=", "b")]`,
    `["&", "|", ("foo", "=", "a"), ("bar", "=", "b"), ("integer", ">", 0)]`,
    `["!", "&", ("foo", "=", "a"), ("integer", "=", 1)]`,
    `["!", "|", ("foo", "=", "a"), ("integer", "=", 1)]`,
    `[("foo", "in", ["a", "b"])]`,
    `[("foo", "not in", ["a"])]`,
    `[("foo_ids", "in", [1, 2])]`,
    `[("foo_ids", "not in", [1])]`,
    `[("boolean_field", "=", True)]`,
    `[("boolean_field", "!=", True)]`,
    `[("foo", "like", "a")]`,
    `[("foo", "ilike", "A")]`,
    `["|", ("foo", "=", False), "&", ("integer", ">=", 1), ("integer", "<=", 3)]`,
    `["&", ("integer", ">=", 1), ("integer", "<=", 5)]`,
    `["&", ("integer", ">", 0), ("integer", "<", 5)]`,
    `["!", "&", ("integer", ">=", 1), ("integer", "<=", 5)]`,
    `["&", ("date_field", ">=", "2024-01-01"), ("date_field", "<=", "2024-12-31")]`,
    `["!", "&", ("date_field", ">=", "2024-01-01"), ("date_field", "<=", "2024-12-31")]`,
    `["&", ("datetime_field", ">=", "2024-01-01 00:00:00"), ("datetime_field", "<=", "2024-12-31 23:59:59")]`,
    `[("date_field", "!=", False)]`,
    `[("date_field", "=", False)]`,
    `[("foo", "=like", "a%")]`,
    `[("foo", "=ilike", "A%")]`,
];

test("domain -> tree -> domain preserves record matching", () => {
    const mismatches = [];
    let checked = 0;
    for (const distributeNot of [false, true]) {
        for (const domain of DOMAINS) {
            const roundTripped = domainFromTree(
                introduceVirtualOperators(
                    constructTreeFromDomain(domain, distributeNot),
                    options,
                ),
            );
            for (const record of RECORDS) {
                const before = new Domain(domain).contains(record);
                const after = new Domain(roundTripped).contains(record);
                checked++;
                if (before !== after) {
                    mismatches.push(
                        `distributeNot=${distributeNot} ${domain}\n    -> ${roundTripped}\n    record=${JSON.stringify(record)} ${before} != ${after}`,
                    );
                }
            }
        }
    }
    expect(mismatches).toEqual([], {
        message: `${mismatches.length} semantic mismatches:\n  ${mismatches.join("\n  ")}`,
    });
    expect(checked).toBe(DOMAINS.length * RECORDS.length * 2);
});
