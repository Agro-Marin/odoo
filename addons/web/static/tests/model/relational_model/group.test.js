// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Group } from "@web/model/relational_model/group";

describe.current.tags("headless");

describe("Group._deleteRecords count integrity", () => {
    test("does not decrement count when the unlink is vetoed", async () => {
        const group = Object.create(Group.prototype);
        group.count = 5;
        group.list = { _deleteRecords: async () => false };

        const result = await group._deleteRecords([{ resId: 1 }, { resId: 2 }]);

        expect(result).toBe(false);
        expect(group.count).toBe(5);
    });

    test("decrements count when the unlink succeeds", async () => {
        const group = Object.create(Group.prototype);
        group.count = 5;
        group.list = { _deleteRecords: async () => true };

        const result = await group._deleteRecords([{ resId: 1 }, { resId: 2 }]);

        expect(result).toBe(true);
        expect(group.count).toBe(3);
    });
});

describe("Group._addRecord resId dedupe", () => {
    function makeGroup(records) {
        const group = Object.create(Group.prototype);
        group.count = records.length;
        const added = [];
        group.list = {
            records,
            _addRecord: (record, index) => added.push({ record, index }),
        };
        return { group, added };
    }

    test("skips a record whose resId is already present", () => {
        const existing = { resId: 7 };
        const { group, added } = makeGroup([existing]);

        group._addRecord({ resId: 7 }, 0);

        expect(added.length).toBe(0);
        expect(group.count).toBe(1);
    });

    test("adds a record with a new resId", () => {
        const { group, added } = makeGroup([{ resId: 7 }]);

        group._addRecord({ resId: 9 }, 1);

        expect(added.length).toBe(1);
        expect(group.count).toBe(2);
    });

    test("always adds a new (resId-less) record", () => {
        const { group, added } = makeGroup([{ resId: 7 }]);

        group._addRecord({ resId: false, _virtualId: "virt-1" }, 0);

        expect(added.length).toBe(1);
        expect(group.count).toBe(2);
    });
});
