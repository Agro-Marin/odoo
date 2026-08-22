// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

describe.current.tags("headless");

const SERVER_ROWS = {
    1: { id: 1, display_name: "Rec 1" },
    2: { id: 2, display_name: "Rec 2" },
    3: { id: 3, display_name: "Rec 3" },
    99: { id: 99, display_name: "Rec 99" },
};

/**
 * @param {{ resIds?: number[], deleted?: Set<number> }} [options]
 */
function makeList({ resIds = [], deleted = new Set() } = {}) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) =>
            ids.filter((id) => !deleted.has(id)).map((id) => SERVER_ROWS[id]),
    };
    const config = {
        resModel: "res.partner",
        activeFields: { display_name: makeActiveField() },
        fields: { display_name: { type: "char", name: "display_name" } },
        relationField: false,
        offset: 0,
        limit: 40,
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
    return new StaticList(/** @type {any} */ (model), config, data, {
        parent,
        onUpdate: async () => {},
    });
}

describe("StaticList._replaceWith partial server response", () => {
    test("a concurrently-deleted id is dropped, not left as an undefined hole", async () => {
        const list = makeList({ resIds: [1], deleted: new Set([99]) });

        await list._replaceWith([1, 2, 99]);

        expect(list.records.includes(/** @type {any} */ (undefined))).toBe(false);
        expect(list.records.map((r) => r.resId)).toEqual([1, 2]);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);
    });

    test("the phantom id is not shipped in the SET command", async () => {
        const list = makeList({ resIds: [1], deleted: new Set([99]) });

        await list._replaceWith([1, 2, 99]);

        expect(list._commands).toEqual([x2ManyCommands.set([1, 2])]);
    });

    test("a full response still keeps every id (guard is inert on the happy path)", async () => {
        const list = makeList({ resIds: [1] });

        await list._replaceWith([1, 2, 3, 99]);

        expect(list.records.map((r) => r.resId)).toEqual([1, 2, 3, 99]);
        expect(list._currentIds).toEqual([1, 2, 3, 99]);
        expect(list.count).toBe(4);
    });
});
