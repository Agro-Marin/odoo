// @ts-check

/**
 * ``Group._useGroupCountForList`` replaces a TRUNCATED list count with the
 * group's own (uncapped) one from ``formatted_read_group``.
 *
 * The condition is ``list.hasLimitedCount``, set by
 * ``DynamicRecordList._updateCount`` exactly when it truncated — not a
 * comparison of ``count`` against ``config.countLimit``. A group's list config
 * has no ``countLimit`` until its first ``_loadData``, so that comparison ran
 * ``number === undefined`` on the initial read_group-embedded load; it returned
 * the right answer there only because that count was never capped to begin
 * with. The exact-boundary case below is the one where the two formulations
 * could visibly disagree.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Group } from "@web/model/relational_model/group";

/**
 * @param {{ groupCount: number, listCount: number, hasLimitedCount: boolean,
 *           isGrouped?: boolean, countLimit?: number }} options
 */
function makeGroup({
    groupCount,
    listCount,
    hasLimitedCount,
    isGrouped = false,
    countLimit,
}) {
    const group = Object.create(Group.prototype);
    group.count = groupCount;
    group.list = {
        isGrouped,
        count: listCount,
        hasLimitedCount,
        config: { countLimit },
    };
    return group;
}

describe("Group._useGroupCountForList", () => {
    test("adopts the group count when the list truncated", () => {
        const group = makeGroup({
            groupCount: 25000,
            listCount: 10000,
            hasLimitedCount: true,
            countLimit: 10000,
        });
        group._useGroupCountForList();
        expect(group.list.count).toBe(25000);
    });

    test("leaves an untruncated count alone", () => {
        const group = makeGroup({
            groupCount: 7,
            listCount: 7,
            hasLimitedCount: false,
            countLimit: 10000,
        });
        group._useGroupCountForList();
        expect(group.list.count).toBe(7);
    });

    test("leaves the initial read_group count alone (no countLimit yet)", () => {
        const group = makeGroup({
            groupCount: 42,
            listCount: 42,
            hasLimitedCount: false,
        });
        group._useGroupCountForList();
        expect(group.list.count).toBe(42);
    });

    test("a true count that equals countLimit is not treated as truncated", () => {
        // The old comparison fired here purely because the numbers matched.
        // Harmless when the group agrees, but it was reading a coincidence as
        // a signal.
        const group = makeGroup({
            groupCount: 10000,
            listCount: 10000,
            hasLimitedCount: false,
            countLimit: 10000,
        });
        group._useGroupCountForList();
        expect(group.list.count).toBe(10000);
    });

    test("never touches a nested grouped list", () => {
        const group = makeGroup({
            groupCount: 25000,
            listCount: 3,
            hasLimitedCount: true,
            isGrouped: true,
        });
        group._useGroupCountForList();
        expect(group.list.count).toBe(3);
    });
});
