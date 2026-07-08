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
