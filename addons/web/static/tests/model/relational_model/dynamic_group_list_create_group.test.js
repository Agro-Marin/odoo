// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

describe.current.tags("headless");

function makeList(/** @type {any[]} */ groups = []) {
    const list = Object.create(DynamicGroupList.prototype);
    list.groups = [...groups];
    list.count = groups.length;
    list._config = {
        domain: [],
        orderBy: [],
        groupBy: ["partner_id"],
        context: {},
        resModel: "res.model",
        fields: {
            partner_id: {
                name: "partner_id",
                relation: "res.partner",
                type: "many2one",
            },
        },
        activeFields: {},
        fieldsToAggregate: [],
        groups: {},
    };
    list.model = {
        initialLimit: 80,
        orm: { call: async () => [42], write: async () => {} },
        _patchConfig: () => {},
    };
    list._createGroupDatapoint = (/** @type {any} */ data) => ({
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

        expect(list.groups.length).toBe(3);
        expect(list.count).toBe(3);
    });
});
