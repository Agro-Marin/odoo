// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    defineModels,
    fields,
    getService,
    makeMockEnv,
    models,
} from "@web/../tests/web_test_helpers";
import { Domain } from "@web/core/domain";
import { constructDomainFromTree } from "@web/core/tree/construct_domain_from_tree";
import { constructTreeFromDomain } from "@web/core/tree/construct_tree_from_domain";
import { simplifyTree } from "@web/core/tree/tree_processor_service";

class Partner extends models.Model {
    qty = fields.Integer({ string: "Qty" });
    qty2 = fields.Integer({ string: "Qty2" });
    qty3 = fields.Integer({ string: "Qty3" });
    qty4 = fields.Integer({ string: "Qty4" });
    manager_id = fields.Many2one({ string: "Manager", relation: "partner" });
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

test("a negated `=` is not absorbed into a sibling's merged `in`", async () => {
    await makeMockEnv();
    // `qty != 1 or qty = 2` matches almost every record; merging it into
    // `qty in [1, 2]` would invert the meaning.
    const description = await describe(["|", "!", ["qty", "=", 1], ["qty", "=", 2]]);
    expect(description).toBe("Qty not = 1 or Qty = 2");
});

test("a negated `in` is not absorbed into a sibling's merged `in`", async () => {
    await makeMockEnv();
    const description = await describe([
        "|",
        "!",
        ["qty", "in", [1, 3]],
        ["qty", "=", 2],
    ]);
    expect(description).toBe("Qty not = ( 1 or 3 ) or Qty = 2");
});

test("value list of exactly `limit` items is shown in full (no spurious ellipsis)", async () => {
    await makeMockEnv();
    const description = await describe([["qty", "in", [1, 2, 3, 4, 5]]], 5);
    expect(description).not.toInclude("...");
    expect(description).toInclude("5");
});

test("value list longer than `limit` is truncated with an ellipsis", async () => {
    await makeMockEnv();
    const description = await describe([["qty", "in", [1, 2, 3, 4, 5, 6]]], 5);
    expect(description).toInclude("...");
    expect(description).not.toInclude("6");
});

test("merging two paths under OR keeps every unrelated sibling", async () => {
    await makeMockEnv();
    const description = await describe([
        "|",
        "|",
        "|",
        "|",
        "|",
        ["qty", "=", 1],
        ["qty", "=", 2],
        ["qty2", "=", 3],
        ["qty2", "=", 4],
        ["qty3", "=", 5],
        ["qty4", "=", 6],
    ]);
    expect(description).toBe(
        "Qty = ( 1 or 2 ) or Qty2 = ( 3 or 4 ) or Qty3 = 5 or Qty4 = 6",
    );
});

test("a second merge does not overwrite a later non-mergeable sibling", async () => {
    await makeMockEnv();
    // Counterexample found by fuzzing simplifyTree for semantic equivalence:
    // the `qty3 != 1` leaf was overwritten by the `qty2` merge and vanished.
    const description = await describe([
        "|",
        "|",
        "|",
        "|",
        ["qty", "=", 3],
        ["qty", "=", 1],
        ["qty2", "in", [1]],
        ["qty2", "in", [2]],
        ["qty3", "!=", 1],
    ]);
    expect(description).toBe("Qty = ( 3 or 1 ) or Qty2 = ( 1 or 2 ) or Qty3 not = 1");
});

test("a 3-way merge followed by a 2-way merge leaves no gap", async () => {
    await makeMockEnv();
    const description = await describe([
        "|",
        "|",
        "|",
        "|",
        ["qty", "=", 1],
        ["qty", "=", 2],
        ["qty", "=", 3],
        ["qty2", "=", 4],
        ["qty2", "=", 5],
    ]);
    expect(description).toBe("Qty = ( 1 or 2 or 3 ) or Qty2 = ( 4 or 5 )");
});

test("makeGetConditionDescription survives a doubly-merged OR tree", async () => {
    await makeMockEnv();
    const treeProcessor = getService("tree_processor");
    const tree = await treeProcessor.treeFromDomain("partner", [
        "|",
        "|",
        "|",
        "|",
        ["qty", "=", 1],
        ["qty", "=", 2],
        ["qty", "=", 3],
        ["qty2", "=", 4],
        ["qty2", "=", 5],
    ]);
    const getDescription = await treeProcessor.makeGetConditionDescription(
        "partner",
        tree,
    );
    expect(typeof getDescription).toBe("function");
});

test("negated OR collapsing to one merged `in` keeps its negation", async () => {
    await makeMockEnv();
    const treeProcessor = getService("tree_processor");
    const tree = await treeProcessor.treeFromDomain(
        "partner",
        ["!", "|", ["qty", "=", 1], ["qty", "=", 2]],
        false,
    );
    const description = await treeProcessor.getDomainTreeDescription("partner", tree);
    expect(description).toInclude("not");
});

/**
 * `simplifyTree` rewrites a tree that is then rendered as text, so its one hard
 * invariant is that it must not change which records the tree describes. Each
 * case below is a domain whose simplification once changed that record set;
 * they were found by fuzzing the rewrite against `Domain.contains`.
 */
const SEMANTIC_CORPUS = [
    ["|", "!", ["a", "=", 1], ["a", "=", 2]],
    ["|", "!", ["a", "in", [1, 3]], ["a", "=", 2]],
    [
        "|",
        "|",
        "|",
        "|",
        ["c", "=", 3],
        ["c", "=", 1],
        ["e", "in", [1]],
        ["e", "in", [2]],
        ["d", "!=", 1],
    ],
    [
        "&",
        ["c", "!=", 3],
        "&",
        "|",
        ["a", "=", 3],
        "!",
        ["a", "in", [3]],
        "!",
        ["c", "=", 1],
    ],
    [
        "|",
        "|",
        "|",
        "|",
        "|",
        ["a", "=", 1],
        ["a", "=", 2],
        ["b", "=", 3],
        ["b", "=", 4],
        ["c", "=", 5],
        ["d", "=", 6],
    ],
    [
        "|",
        "|",
        "|",
        "|",
        ["a", "=", 1],
        ["a", "=", 2],
        ["a", "=", 3],
        ["b", "=", 4],
        ["b", "=", 5],
    ],
    ["!", "|", ["a", "=", 1], ["a", "=", 2]],
];

const CORPUS_RECORDS = [];
for (const a of [1, 2, 3, false]) {
    for (const c of [1, 2, 3, false]) {
        for (const d of [1, 6, false]) {
            CORPUS_RECORDS.push({ a, b: 3, c, d, e: 1 });
            CORPUS_RECORDS.push({ a, b: 4, c, d, e: 2 });
        }
    }
}

test("simplifyTree preserves the record set it describes", () => {
    for (const domain of SEMANTIC_CORPUS) {
        for (const distributeNot of [true, false]) {
            const tree = constructTreeFromDomain(domain, distributeNot);
            const before = new Domain(constructDomainFromTree(tree));
            const after = new Domain(constructDomainFromTree(simplifyTree(tree)));
            for (const record of CORPUS_RECORDS) {
                expect(after.contains(record)).toBe(before.contains(record), {
                    message: `${JSON.stringify(domain)} distributeNot=${distributeNot} on ${JSON.stringify(record)}`,
                });
            }
        }
    }
});

test("a tree's field defs and display names are resolved once, not once per leaf", async () => {
    // `describeSimplifiedTree` used to build a fresh `makeGetConditionDescription`
    // for every leaf, re-running the whole-tree resolution N times and defeating
    // the batching those helpers exist to provide. It also made display-name
    // batching depend on microtask alignment: leaves at different depths reached
    // `loadDisplayNames` on different ticks and fragmented into separate RPCs.
    await makeMockEnv();
    const field = getService("field");
    const name = getService("name");
    let loadFieldInfoCalls = 0;
    let loadDisplayNamesCalls = 0;
    // Counted with the receiver preserved. These used to capture the method and
    // call it back bare — `origLoadFieldInfo(...args)` — which happened to work
    // only because both services were closures whose "methods" ignored `this`.
    // `field` is a class now, so a bare call arrives with `this` undefined and
    // throws on its first internal `this.loadPath(...)`.
    const origLoadFieldInfo = field.loadFieldInfo;
    const origLoadDisplayNames = name.loadDisplayNames;
    field.loadFieldInfo = (...args) => {
        loadFieldInfoCalls++;
        return origLoadFieldInfo.call(field, ...args);
    };
    name.loadDisplayNames = (...args) => {
        loadDisplayNamesCalls++;
        return origLoadDisplayNames.call(name, ...args);
    };

    const treeProcessor = getService("tree_processor");
    // Nested AND: the 6 leaves sit at depths 1..6.
    const domain = ["&", "&", "&", "&", "&"];
    for (let i = 0; i < 6; i++) {
        domain.push(["manager_id", "in", [i + 1]]);
    }
    const tree = await treeProcessor.treeFromDomain("partner", domain);
    loadFieldInfoCalls = 0;
    loadDisplayNamesCalls = 0;
    await treeProcessor.getDomainTreeDescription("partner", tree);

    // One path (`manager_id`) and one co-model (`partner`) across all 6 leaves.
    expect(loadFieldInfoCalls).toBe(1);
    expect(loadDisplayNamesCalls).toBe(1);
});

test("a sub-expression inherits the caller's value and path limits", async () => {
    await makeMockEnv();
    const treeProcessor = getService("tree_processor");
    const domain = [
        ["manager_id", "any", [["manager_id.qty", "in", [1, 2, 3, 4, 5, 6, 7, 8]]]],
    ];
    const tree = await treeProcessor.treeFromDomain("partner", domain);

    // `limit`/`pathLimit` are threaded through the whole description recursion
    // for the sole benefit of this nested call. Dropping them silently handed
    // the sub-domain the DEFAULTS (5 values, unlimited path segments).
    expect(
        await treeProcessor.getDomainTreeDescription("partner", tree, false, 2, 1),
    ).toBe("Manager : ( Manager... = 1 or ... )");

    expect(await treeProcessor.getDomainTreeDescription("partner", tree)).toBe(
        "Manager : ( Manager \u2794 Qty = 1 or 2 or 3 or 4 or ... )",
    );
});
