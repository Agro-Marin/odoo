// @ts-check

import { expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
import { complexCondition, condition, connector } from "@web/core/tree/condition_tree";
import { constructDomainFromTree } from "@web/core/tree/construct_domain_from_tree";
import { domainFromTree } from "@web/core/tree/domain_from_tree";

test("domainFromTree", async () => {
    await makeMockEnv();
    const toTest = [
        {
            tree: condition("foo", "=", false),
            result: `[("foo", "=", False)]`,
        },
        {
            tree: condition("foo", "=", false, true),
            result: `["!", ("foo", "=", False)]`,
        },
        {
            tree: condition("foo", "=?", false),
            result: `[("foo", "=?", False)]`,
        },
        {
            tree: condition("foo", "=?", false, true),
            result: `["!", ("foo", "=?", False)]`,
        },
        {
            tree: condition("foo", "starts with", "hello"),
            result: `[("foo", "=ilike", "hello%")]`,
        },
    ];
    for (const { tree, result } of toTest) {
        expect(domainFromTree(tree).replace(/[\s\n]+/g, "")).toBe(
            result.replace(/[\s\n]+/g, ""),
        );
    }
});

test("a negated connector folded onto a complex condition keeps its negation", async () => {
    await makeMockEnv();
    const tree = connector("&", [complexCondition("a.b")], true);
    expect(domainFromTree(tree)).toBe(`["!", (bool(a.b), "=", 1)]`);
    expect(constructDomainFromTree(tree)).toBe(domainFromTree(tree));
});

test("a complex condition without negation is unchanged", async () => {
    await makeMockEnv();
    const tree = connector("&", [complexCondition("a.b")], false);
    expect(domainFromTree(tree)).toBe(`[(bool(a.b), "=", 1)]`);
});
