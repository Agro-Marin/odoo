// @ts-check

/**
 * Regression test for the partial-response hole in ``StaticList._load``.
 *
 * ``_loadRecords`` (RelationalModel) only throws when *zero* rows come back; a
 * partial response — a linked x2many row unlinked server-side between the page
 * request and its load — returns fewer rows. ``_load`` used to map every
 * requested id through ``_cache`` unconditionally, so an id that never landed
 * became an ``undefined`` hole in ``records`` that the list/kanban renderer then
 * crashed on (``record.data`` on ``undefined``). It must instead drop the
 * missing ids (and trim ``_currentIds``), mirroring the guard in
 * static_list_command_engine.js.
 *
 * Uses the REAL StaticList and RelationalRecord against a mock model, in the
 * style of static_list_link_full_page.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const SERVER_ROWS = {
    1: { id: 1, display_name: "Rec 1" },
    2: { id: 2, display_name: "Rec 2" },
    3: { id: 3, display_name: "Rec 3" },
    99: { id: 99, display_name: "Rec 99" },
};

function makeList({ resIds = [], limit = 2, deleted = new Set() } = {}) {
    const loadedResIds = [];
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => {
            loadedResIds.push([...ids]);
            return ids.filter((id) => !deleted.has(id)).map((id) => SERVER_ROWS[id]);
        },
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
    const data = resIds.filter((id) => !deleted.has(id)).map((id) => SERVER_ROWS[id]);
    const list = new StaticList(model, config, data, {
        parent,
        onUpdate: async () => {},
    });
    return { list, loadedResIds };
}

describe("StaticList._load partial server response", () => {
    test("a concurrently-deleted id is dropped, not left as an undefined hole", async () => {
        const { list } = makeList({
            resIds: [1, 2, 3, 99],
            limit: 2,
            deleted: new Set([99]),
        });
        expect(list.records.map((r) => r.resId)).toEqual([1, 2]);

        await list._load({ offset: 2 });

        expect(list.records.includes(undefined)).toBe(false);
        expect(list.records.map((r) => r.resId)).toEqual([3]);
        expect(list.records[0].data.display_name).toBe("Rec 3");
        expect(list._currentIds).toEqual([1, 2, 3]);
    });

    test("a full response still keeps every id (guard is inert on the happy path)", async () => {
        const { list } = makeList({ resIds: [1, 2, 3, 99], limit: 2 });

        await list._load({ offset: 2 });

        expect(list.records.map((r) => r.resId)).toEqual([3, 99]);
        expect(list._currentIds).toEqual([1, 2, 3, 99]);
    });
});
