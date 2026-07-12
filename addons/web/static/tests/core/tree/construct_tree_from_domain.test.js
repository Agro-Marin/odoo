// @ts-check

import { expect, test } from "@odoo/hoot";
import { condition, connector, Expression } from "@web/core/tree/condition_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";

test("constructTreeFromDomain", async () => {
    const toTest = [
        { domain: `[]`, tree: connector("&") },
        { domain: `[(0, "=", 1)]`, tree: condition(0, "=", 1) },
        { domain: `[(1, "=", 1)]`, tree: condition(1, "=", 1) },
        { domain: `["!", (0, "=", 1)]`, tree: condition(0, "=", 1, true) },
        { domain: `["!", (1, "=", 1)]`, tree: condition(1, "=", 1, true) },
    ];
    for (const { domain, tree } of toTest) {
        expect(constructTreeFromDomain(domain)).toEqual(tree);
    }
});

test("constructTreeFromDomain: connectors, negation and distribution", () => {
    expect(constructTreeFromDomain(`["!", "|", ("a", "=", 1), ("b", "=", 2)]`)).toEqual(
        connector("|", [condition("a", "=", 1), condition("b", "=", 2)], true),
    );
    expect(
        constructTreeFromDomain(`["!", "|", ("a", "=", 1), ("b", "=", 2)]`, true),
    ).toEqual(
        connector("&", [condition("a", "=", 1, true), condition("b", "=", 2, true)]),
    );
    // same-value children are flattened into the parent connector
    expect(
        constructTreeFromDomain(
            `["&", "&", ("a", "=", 1), ("b", "=", 2), ("c", "=", 3)]`,
        ),
    ).toEqual(
        connector("&", [
            condition("a", "=", 1),
            condition("b", "=", 2),
            condition("c", "=", 3),
        ]),
    );
    expect(constructTreeFromDomain(`["!", "!", ("a", "=", 1)]`)).toEqual(
        condition("a", "=", 1),
    );
});

test("constructTreeFromDomain: large domains do not overflow the stack", () => {
    // The normalized prefix chain ["&", "&", ..., leaf, ...] used to be
    // consumed recursively (depth O(N)) with an O(N²) tail spread.
    const N = 5000;
    const domain = [
        ...Array(N - 1).fill("&"),
        ...Array.from({ length: N }, (_, i) => ["f", "=", i]),
    ];
    const tree = /** @type {any} */ (constructTreeFromDomain(domain));
    expect(tree.type).toBe("connector");
    expect(tree.value).toBe("&");
    expect(tree.children.length).toBe(N);
    expect(tree.children[0]).toEqual(condition("f", "=", 0));
    expect(tree.children[N - 1]).toEqual(condition("f", "=", N - 1));
});

test("'any' with an Expression value is left untouched (not wrapped in a list)", () => {
    // `[("partner_id", "any", uid)]` where the value is a free variable used to
    // round-trip to `[("partner_id", "any", [uid])]` — a nested invalid domain.
    const tree = /** @type {any} */ (
        constructTreeFromDomain(`[("partner_id", "any", uid)]`)
    );
    const cond = tree.type === "condition" ? tree : tree.children[0];
    expect(cond.value).toBeInstanceOf(Expression);
    expect(Array.isArray(cond.value)).toBe(false);
});
