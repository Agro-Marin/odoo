// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    collectPendingCommands,
    healSubtreeReplayFailures,
    walkX2manySubtree,
} from "@web/model/relational_model/x2many_tree";

describe.current.tags("headless");

/**
 * @param {Record<string, any>} lists
 * @returns {any}
 */
function makeRecord(lists) {
    return {
        activeFields: Object.fromEntries(Object.keys(lists).map((k) => [k, {}])),
        fields: Object.fromEntries(
            Object.keys(lists).map((k) => [k, { type: "one2many" }]),
        ),
        data: lists,
    };
}

/**
 * @param {any[]} [cachedRecords]
 * @param {Promise<any> | null} [pendingCommands]
 * @returns {any}
 */
function makeList(cachedRecords = [], pendingCommands = null) {
    return {
        cachedRecords,
        pendingCommands,
        healed: 0,
        healFailedReplay() {
            this.healed++;
        },
    };
}

describe("walkX2manySubtree", () => {
    test("yields every list, depth first, once", () => {
        const leaf = makeList();
        const child = makeRecord({ grandchildren: leaf });
        const top = makeList([child]);
        const other = makeList();
        const record = makeRecord({ lines: top, tags: other });

        expect([...walkX2manySubtree(record)].map(([name]) => name)).toEqual(
            ["lines", "grandchildren", "tags"],
            {
                message:
                    "a list is yielded before its rows' own lists — the order the " +
                    "two callers relied on when each spelled the walk out itself",
            },
        );
    });

    test("a list reachable twice is yielded once", () => {
        const shared = makeList();
        const record = makeRecord({ a: shared, b: shared });
        expect([...walkX2manySubtree(record)]).toHaveLength(1);
    });

    test("a cycle through a cached row terminates", () => {
        const list = makeList();
        const record = makeRecord({ lines: list });
        list.cachedRecords = [record];
        expect([...walkX2manySubtree(record)]).toHaveLength(1, {
            message: "`seen` holds records as well as lists, or this never returns",
        });
    });

    test("identity, not id: two datapoints for one row are both visited", () => {
        const a = makeList();
        const b = makeList();
        const record = makeRecord({ a, b });
        expect([...walkX2manySubtree(record)]).toHaveLength(2);
    });
});

describe("the two callers are now the line that differed", () => {
    test("collectPendingCommands gathers from the whole subtree", () => {
        const p1 = Promise.resolve(1);
        const p2 = Promise.resolve(2);
        const leaf = makeList([], p2);
        const child = makeRecord({ deep: leaf });
        const record = makeRecord({
            lines: makeList([child], p1),
            quiet: makeList(),
        });
        expect(collectPendingCommands(record)).toEqual([p1, p2]);
    });

    test("healSubtreeReplayFailures heals the whole subtree", () => {
        const leaf = makeList();
        const child = makeRecord({ deep: leaf });
        const top = makeList([child]);
        healSubtreeReplayFailures(makeRecord({ lines: top }));
        expect([top.healed, leaf.healed]).toEqual([1, 1]);
    });

    test("both walk PROPERTY-backed lists too, unlike buildCommitSpec", () => {
        const list = makeList([], Promise.resolve(1));
        const record = makeRecord({ "properties.tags": list });
        record.fields["properties.tags"].relatedPropertyField = { name: "properties" };
        expect(collectPendingCommands(record)).toHaveLength(1, {
            message:
                "`allX2manyLists`, not `x2manyLists` — a property list can have an " +
                "in-flight command replay like any other",
        });
    });
});
