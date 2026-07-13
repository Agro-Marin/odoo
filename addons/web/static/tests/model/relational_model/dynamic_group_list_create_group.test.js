// @ts-check

/**
 * Focused unit tests for DynamicGroupList._createGroup count integrity
 * (delegation-pattern mocks, built on the real DynamicGroupList.prototype).
 *
 * this.count is the NUMBER OF GROUPS for a DynamicGroupList (set from
 * data.length in _setData, decremented by _removeGroup). Creating a group must
 * increment it symmetrically, otherwise the grouped pager total and
 * isRecordCountTrustable drift by one after every "Add column".
 */

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

function makeList(groups = []) {
    const list = Object.create(DynamicGroupList.prototype);
    list.groups = [...groups];
    list.count = groups.length;
    list.domain = [];
    list.orderBy = [];
    list.groupBy = ["partner_id"];
    list.context = {};
    list.groupByField = {
        name: "partner_id",
        relation: "res.partner",
        type: "many2one",
    };
    list.config = {
        resModel: "res.model",
        fields: {},
        activeFields: {},
        fieldsToAggregate: [],
        groups: {},
    };
    list.model = {
        initialLimit: 80,
        orm: { call: async () => [42] }, // name_create returns [id]
        _patchConfig: () => {},
    };
    // Stub datapoint creation / resequence so the test exercises only the
    // count bookkeeping, not the ORM / server-side plumbing.
    list._createGroupDatapoint = (data) => ({
        id: `g-${data.value}`,
        value: data.value,
    });
    list._resequence = async () => {};
    return list;
}

describe("DynamicGroupList._createGroup count integrity", () => {
    test("increments the group count when creating the first group", async () => {
        const list = makeList([]);

        await list._createGroup("Foo");

        expect(list.groups.length).toBe(1);
        expect(list.count).toBe(1);
    });

    test("increments the group count when appending to existing groups", async () => {
        const list = makeList([
            { id: "g-1", value: 1 },
            { id: "g-2", value: 2 },
        ]);

        await list._createGroup("Foo");

        // A 3rd group was appended, and count must track it (was previously
        // left at 2, making the grouped pager total one short).
        expect(list.groups.length).toBe(3);
        expect(list.count).toBe(3);
    });
});
