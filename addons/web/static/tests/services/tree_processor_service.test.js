// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
} from "@web/../tests/web_test_helpers";

class Partner extends models.Model {
    qty = fields.Integer({ string: "Qty" });
}
defineModels([Partner]);

/**
 * @param {any[]} domain
 * @param {number} limit
 * @returns {Promise<string>}
 */
async function describe(domain, limit) {
    const treeProcessor = getService("tree_processor");
    const tree = await treeProcessor.treeFromDomain("partner", domain);
    return treeProcessor.getDomainTreeDescription("partner", tree, false, limit);
}

test("value list of exactly `limit` items is shown in full (no spurious ellipsis)", async () => {
    await makeMockEnv();
    // Exactly `limit` values: nothing is truncated, so no "..." must appear and
    // the last value must still be rendered.
    const description = await describe([["qty", "in", [1, 2, 3, 4, 5]]], 5);
    expect(description).not.toInclude("...");
    expect(description).toInclude("5");
});

test("value list longer than `limit` is truncated with an ellipsis", async () => {
    await makeMockEnv();
    // More than `limit` values: the tail is replaced by "..." and the last
    // values are not rendered.
    const description = await describe([["qty", "in", [1, 2, 3, 4, 5, 6]]], 5);
    expect(description).toInclude("...");
    expect(description).not.toInclude("6");
});

test("negated OR collapsing to one merged `in` keeps its negation", async () => {
    await makeMockEnv();
    const treeProcessor = getService("tree_processor");
    // distributeNot=false keeps the connector's `negate` flag on the OR node
    // instead of pushing it down to the leaves (as happens in debug mode).
    const tree = await treeProcessor.treeFromDomain(
        "partner",
        ["!", "|", ["qty", "=", 1], ["qty", "=", 2]],
        false,
    );
    // simplifyTree merges the two same-path `=` conditions into one `in`,
    // collapsing the OR to a single child; the connector's negation must be
    // pushed onto that child, not silently dropped.
    const description = await treeProcessor.getDomainTreeDescription("partner", tree);
    expect(description).toInclude("not");
});
