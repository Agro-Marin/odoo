// @ts-check

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
    expect(domainContainsExpressions(`[("user_id", "in", [uid])]`)).toBe(true);
});

test("a dynamic PATH is an expression", async () => {
    expect(domainContainsExpressions(`[(field_name, "=", 1)]`)).toBe(true);
});

test("an expression inside an `any` subtree is found", async () => {
    expect(
        domainContainsExpressions(`[("partner_id", "any", [("user_id", "=", uid)])]`),
    ).toBe(true);
    expect(
        domainContainsExpressions(`[("partner_id", "any", [("name", "=", "x")])]`),
    ).toBe(false);
});

test("an unparseable domain reports null, not a boolean", async () => {
    expect(domainContainsExpressions(`[(`)).toBe(null);
    expect(domainContainsExpressions(`not a domain`)).toBe(null);
});
