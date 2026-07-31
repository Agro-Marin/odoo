// @ts-check

/**
 * `domainContainsExpressions` decides whether the domain editor may show its
 * visual builder or must fall back to raw text. A false negative silently
 * routes a dynamic domain through the builder, which cannot represent it — so
 * this had no coverage while guarding a data-loss path.
 */

import { describe, expect, test } from "@odoo/hoot";
import { domainContainsExpressions } from "@web/core/tree/domain_contains_expressions";

describe.current.tags("headless");

test("a fully literal domain contains no expressions", async () => {
    expect(domainContainsExpressions(`[]`)).toBe(false);
    expect(domainContainsExpressions(`[("name", "=", "abc")]`)).toBe(false);
    expect(domainContainsExpressions(`["&", ("a", "=", 1), ("b", "in", [1, 2])]`)).toBe(
        false,
    );
    expect(domainContainsExpressions(`[("a", "=", False)]`)).toBe(false);
});

test("a dynamic VALUE is an expression", async () => {
    expect(domainContainsExpressions(`[("user_id", "=", uid)]`)).toBe(true);
    expect(domainContainsExpressions(`[("d", "=", context_today())]`)).toBe(true);
});

test("a dynamic value nested in a list is an expression", async () => {
    // The list branch: `v.some(w => w instanceof Expression)`.
    expect(domainContainsExpressions(`[("user_id", "in", [uid])]`)).toBe(true);
});

test("a dynamic PATH is an expression", async () => {
    expect(domainContainsExpressions(`[(field_name, "=", 1)]`)).toBe(true);
});

test("an expression inside an `any` subtree is found", async () => {
    // The recursive branch: a condition whose value is itself a tree.
    expect(
        domainContainsExpressions(`[("partner_id", "any", [("user_id", "=", uid)])]`),
    ).toBe(true);
    expect(
        domainContainsExpressions(`[("partner_id", "any", [("name", "=", "x")])]`),
    ).toBe(false);
});

test("an unparseable domain reports null, not a boolean", async () => {
    // Callers distinguish "no expressions" from "cannot tell"; collapsing the
    // two would send a broken domain to the visual builder.
    expect(domainContainsExpressions(`[(`)).toBe(null);
    expect(domainContainsExpressions(`not a domain`)).toBe(null);
});
