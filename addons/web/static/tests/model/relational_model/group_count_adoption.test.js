// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Group } from "@web/model/relational_model/group";

/**
 * @param {{ groupCount: number, listCount: number, hasLimitedCount: boolean,
 * isGrouped?: boolean, countLimit?: number }} options
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
