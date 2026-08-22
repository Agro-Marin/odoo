// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const UNLINK = 3;
const SET = 6;

const SERVER_ROWS = {
    1: { id: 1, display_name: "Rec 1" },
    2: { id: 2, display_name: "Rec 2" },
    3: { id: 3, display_name: "Rec 3" },
    4: { id: 4, display_name: "Rec 4" },
    5: { id: 5, display_name: "Rec 5" },
};

function makeList({ resIds = [], limit = 2 } = {}) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => ids.map((id) => SERVER_ROWS[id]),
    };
    const config = {
        resModel: "res.partner",
        activeFields: { display_name: makeActiveField() },
        fields: { display_name: { type: "char", name: "display_name" } },
        relationField: false,
        offset: 0,
        limit,
        resIds,
        orderBy: [],
        context: {},
    };
    const parent = {
        evalContext: {},
        evalContextWithVirtualIds: {},
        _isEvalContextReady: true,
    };
    const data = resIds.map((id) => SERVER_ROWS[id]);
    return new StaticList(model, config, data, {
        parent,
        onUpdate: async () => {},
    });
}

describe("page offset after a shrinking command batch", () => {
    test("an onchange replacing the relation with a shorter one", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4], limit: 2 });
        await list._load({ offset: 2 });
        expect(list.records.map((r) => r.resId)).toEqual([3, 4]);

        await list._applyCommands([[SET, false, [1, 2]]]);

        expect(list.count).toBe(2);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.offset).toBe(0);
        expect(list.records.map((r) => r?.resId)).toEqual([1, 2]);
    });

    test("unlinking every record of the current page", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4], limit: 2 });
        await list._load({ offset: 2 });
        expect(list.records.map((r) => r.resId)).toEqual([3, 4]);

        await list._applyCommands([
            [UNLINK, 3, false],
            [UNLINK, 4, false],
        ]);

        expect(list.count).toBe(2);
        expect(list.offset).toBe(0);
        expect(list.records.map((r) => r?.resId)).toEqual([1, 2]);
    });

    test("lands on the last page with data, not on the first", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 2 });
        await list._load({ offset: 4 });
        expect(list.records.map((r) => r.resId)).toEqual([5]);

        await list._applyCommands([[UNLINK, 5, false]]);

        expect(list.count).toBe(4);
        expect(list.offset).toBe(2);
        expect(list.records.map((r) => r?.resId)).toEqual([3, 4]);
    });

    test("a page that still holds data keeps its offset", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 2 });
        await list._load({ offset: 2 });
        expect(list.records.map((r) => r.resId)).toEqual([3, 4]);

        await list._applyCommands([[UNLINK, 4, false]]);

        expect(list.count).toBe(4);
        expect(list.offset).toBe(2);
        expect(list.records.map((r) => r?.resId)).toEqual([3, 5]);
    });

    test("emptying the relation returns to the first page", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4], limit: 2 });
        await list._load({ offset: 2 });

        await list._applyCommands([
            [UNLINK, 1, false],
            [UNLINK, 2, false],
            [UNLINK, 3, false],
            [UNLINK, 4, false],
        ]);

        expect(list.count).toBe(0);
        expect(list.offset).toBe(0);
        expect(list.records).toEqual([]);
    });
});
