// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const CREATE = 0;
const DELETE = 2;
const UNLINK = 3;
const LINK = 4;
const CLEAR = 5;

/** @type {Record<number, { id: number, display_name: string }>} */
const SERVER_ROWS = {};
for (let id = 1; id <= 12; id++) {
    SERVER_ROWS[id] = { id, display_name: `Rec ${id}` };
}

function makeList({ resIds = [], limit = 3 } = {}) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => ids.map((id) => SERVER_ROWS[id]),
        _loadNewRecord: async () => ({ display_name: "" }),
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
    return new StaticList(model, config, data, { parent, onUpdate: async () => {} });
}

describe.current.tags("headless");

describe("a batch that removes and adds must not inflate the page", () => {
    test("DELETE + CREATE on a full page leaves limit untouched", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 3 });
        expect(list.records.map((r) => r.resId)).toEqual([1, 2, 3]);

        await list._applyCommands([
            [DELETE, 2, false],
            [CREATE, false, { display_name: "new" }],
        ]);

        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list.records.length).toBe(3);
        expect(list.records.map((r) => r.resId || "new")).toEqual([1, 3, "new"]);
        expect(list.count).toBe(5);
    });

    test("UNLINK + CREATE on a full page leaves limit untouched", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 3 });

        await list._applyCommands([
            [UNLINK, 1, false],
            [CREATE, false, { display_name: "new" }],
        ]);

        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list.records.length).toBe(3);
    });

    test("repeating the batch never accumulates slots", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 3 });
        for (let i = 0; i < 4; i++) {
            const victim = list.records[0];
            await list._applyCommands([
                [DELETE, victim.resId || victim._virtualId, false],
                [CREATE, false, { display_name: `new${i}` }],
            ]);
        }
        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list.records.length).toBe(3);
    });

    test("a CLEAR-led batch re-declaring fewer rows leaves limit untouched", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5], limit: 3 });

        await list._applyCommands([
            [CLEAR, false, false],
            [LINK, 1, SERVER_ROWS[1]],
            [CREATE, false, { display_name: "new" }],
        ]);

        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(0);
        expect(list.records.length).toBe(2);
        expect(list.count).toBe(2);
    });
});

describe("a genuine over-limit add still opens a slot", () => {
    test("CREATE alone on a full page bumps the limit by one", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 3 });

        await list._applyCommands([[CREATE, false, { display_name: "new" }]]);

        expect(list.limit).toBe(4);
        expect(list._tmpIncreaseLimit).toBe(1);
        expect(list.records.length).toBe(4);
    });

    test("two CREATEs on a full page bump it by two", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 3 });

        await list._applyCommands([
            [CREATE, false, { display_name: "a" }],
            [CREATE, false, { display_name: "b" }],
        ]);

        expect(list.limit).toBe(5);
        expect(list._tmpIncreaseLimit).toBe(2);
        expect(list.records.length).toBe(5);
    });

    test("addAndRemove over the limit only opens slots for rows that remain", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 3 });

        await list._applyCommands(
            [
                [UNLINK, 1, false],
                [LINK, 4, SERVER_ROWS[4]],
                [LINK, 5, SERVER_ROWS[5]],
            ],
            { canAddOverLimit: true },
        );

        expect(list.records.length).toBe(4);
        expect(list.limit).toBe(4);
        expect(list._tmpIncreaseLimit).toBe(1);
        expect(list.count).toBe(4);
    });
});

describe("the slot is still handed back on discard", () => {
    test("discard after a genuine bump restores the original limit", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 3 });
        await list._applyCommands([[CREATE, false, { display_name: "new" }]]);
        expect(list.limit).toBe(4);

        list._discard();
        await list._commandsPromise;

        expect(list.limit).toBe(3);
        expect(list._tmpIncreaseLimit).toBe(0);
    });
});
