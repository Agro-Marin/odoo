// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { expressionFromTree } from "@web/core/tree/expression_from_tree";
import { treeFromExpression } from "@web/core/tree/tree_from_expression";
import {
    introduceVirtualOperators,
    virtualOperatorFunctions,
} from "@web/core/tree/virtual_operators";

describe.current.tags("headless");

const options = {
    getFieldDef: (name) => {
        if (["foo", "bar", "char_field"].includes(name)) {
            return { type: "char" };
        }
        if (["foo_ids", "bar_ids"].includes(name)) {
            return { type: "many2many" };
        }
        if (name === "user_id") {
            return { type: "many2one" };
        }
        if (name === "boolean_field") {
            return { type: "boolean" };
        }
        if (name === "date_field") {
            return { type: "date" };
        }
        if (name === "datetime_field") {
            return { type: "datetime" };
        }
        if (["integer", "other_integer"].includes(name)) {
            return { type: "integer" };
        }
        if (name === "float_field") {
            return { type: "float" };
        }
        return null;
    },
};

/**
 * The strongest invariant of the tree stack: converting through a tree and
 * back must reach a FIXPOINT after at most one round trip — a second pass
 * over its own output must be the identity.
 */
test("domain -> tree -> domain reaches a fixpoint after one round trip", () => {
    const corpus = [
        `[]`,
        `[(1, "=", 1)]`,
        `[(0, "=", 1)]`,
        `[("foo", "=", "bar")]`,
        `[("foo", "!=", False)]`,
        `[("foo", "=", False)]`,
        `["!", ("foo", "=", "bar")]`,
        `[("integer", ">", 5)]`,
        `[("integer", "<=", uid)]`,
        `["&", ("foo", "=", "a"), ("integer", "<", 3)]`,
        `["|", ("foo", "=", "a"), ("foo", "=", "b")]`,
        `["&", "&", ("a", "=", 1), ("b", "=", 2), ("c", "=", 3)]`,
        `["|", "|", ("a", "=", 1), ("b", "=", 2), ("c", "=", 3)]`,
        `["&", "|", ("a", "=", 1), ("b", "=", 2), ("c", "=", 3)]`,
        `["!", "&", ("a", "=", 1), ("b", "=", 2)]`,
        `["!", "|", ("a", "=", 1), ("b", "=", 2)]`,
        `[("foo_ids", "in", [1, 2, 3])]`,
        `[("foo_ids", "not in", [1])]`,
        `[("user_id", "in", [1, uid])]`,
        `[("foo", "in", ["a", "b"])]`,
        `[("foo", "like", "abc%")]`,
        `[("foo", "=ilike", "abc%")]`,
        `[("char_field", "=ilike", "abc%")]`,
        `[("boolean_field", "=", True)]`,
        `[("boolean_field", "!=", True)]`,
        `["&", ("integer", ">=", 1), ("integer", "<=", 3)]`,
        `["&", ("float_field", ">=", 1.5), ("float_field", "<=", uid)]`,
        `[("date_field", ">=", "2024-01-01")]`,
        `["&", ("date_field", ">=", "today"), ("date_field", "<", "today +1d")]`,
        `[("line_ids", "any", [("integer", ">", 0)])]`,
        `[("line_ids", "not any", [("a", "=", 1), ("b", "=", 2)])]`,
        `[("foo", "parent_of", [1, 2])]`,
        `[("foo", "=?", context.get("x"))]`,
        `["&", (bool(a), "=", 1), ("foo", "=", "b")]`,
        `["|", ("date_field", "=", False), "&", ("integer", ">=", 1), ("integer", "<=", 3)]`,
    ];
    for (const domain of corpus) {
        const once = domainFromTree(
            introduceVirtualOperators(constructTreeFromDomain(domain), options),
        );
        const twice = domainFromTree(
            introduceVirtualOperators(constructTreeFromDomain(once), options),
        );
        expect(twice).toBe(once);
    }
});

test("expression -> tree -> expression reaches a fixpoint after one round trip", () => {
    const corpus = [
        `True`,
        `False`,
        `not 1`,
        `foo == "bar"`,
        `not foo`,
        `foo and bar`,
        `foo or not bar`,
        `integer > 5 and integer <= 10`,
        `integer >= 1 and integer <= 3`,
        `integer >= 1 and integer <= uid`,
        `foo == "a" or foo == "b"`,
        `not (foo == "a" and bar == "b")`,
        `set(foo_ids).intersection([1, 2])`,
        `not set(foo_ids).intersection([1, 2])`,
        `set(foo_ids).intersection()`,
        `foo in ["a", "b"]`,
        `integer in [1, 2, 3]`,
        `context.get("x")`,
        `not context.get("x")`,
        `context.get("x") and foo == "a"`,
        `foo == "a" if bar else foo == "b"`,
        `integer > 5 if context.get("x") else integer < 2`,
        `uid`,
        `foo <> "a"`,
        `a <> b`,
        `boolean_field`,
        `not boolean_field`,
        `boolean_field == True`,
        `float_field >= 0.5`,
        `1 <= integer`,
        `(foo == "a" or bar == "b") and integer == 1`,
    ];
    const exprOptions = { ...options, generateSmartDates: false };
    for (const expression of corpus) {
        const once = expressionFromTree(
            treeFromExpression(expression, exprOptions),
            exprOptions,
        );
        const twice = expressionFromTree(
            treeFromExpression(once, exprOptions),
            exprOptions,
        );
        expect(twice).toBe(once);
    }
});

test("introduce/eliminate virtual operators are inverse transformation chains", () => {
    // The two applyTransformations call sites run their passes in array
    // order; each list must stay the exact reverse of the other (ordering
    // contract in virtual_operators.js).
    const domain = `["&", "&", ("char_field", "=ilike", "a%"), ("integer", ">=", 1), ("integer", "<=", 3)]`;
    const tree = introduceVirtualOperators(constructTreeFromDomain(domain), options);
    expect(domainFromTree(tree)).toBe(domain);
    // patchability: the two exported chains are reachable via the
    // virtualOperatorFunctions indirection
    expect(
        virtualOperatorFunctions.introduceVirtualOperators(
            constructTreeFromDomain(domain),
            options,
        ),
    ).toEqual(tree);
});
