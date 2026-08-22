// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/core/network/commands";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";
import { applyCommands } from "@web/model/relational_model/static_list_command_engine";
import { sort } from "@web/model/relational_model/static_list_sort";

const { CLEAR, DELETE, LINK, UNLINK, UPDATE } = x2ManyCommands;

/** @type {Record<number, { id: number, display_name: string }>} */
const SERVER_ROWS = {
    1: { id: 1, display_name: "C" },
    2: { id: 2, display_name: "A" },
    3: { id: 3, display_name: "B" },
    99: { id: 99, display_name: "Z" },
};

/** @type {Record<number, string>} */
const NAMES = {
    0: "CREATE",
    1: "UPDATE",
    2: "DELETE",
    3: "UNLINK",
    4: "LINK",
    5: "CLEAR",
    6: "SET",
};
const readable = (/** @type {[number, number][]} */ commands) =>
    commands.map(([code, id]) => `${NAMES[code]}:${id}`);

/**
 * @param {{ resIds?: number[], limit?: number, deleted?: Set<number> }} [options]
 */
function makeList({ resIds = [], limit = 10, deleted = new Set() } = {}) {
    /** @type {any} */
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        _loadRecords: async (/** @type {{ resIds: number[] }} */ { resIds: ids }) =>
            ids.filter((id) => !deleted.has(id)).map((id) => SERVER_ROWS[id]),
    };
    /** @type {any} */
    const config = {
        resModel: "res.partner",
        activeFields: { display_name: makeActiveField() },
        fields: { display_name: { type: "char", name: "display_name" } },
        relationField: false,
        offset: 0,
        limit,
        resIds,
        orderBy: /** @type {any[]} */ ([]),
        context: {},
    };
    /** @type {any} */
    const parent = {
        evalContext: {},
        evalContextWithVirtualIds: {},
        _isEvalContextReady: true,
    };
    const data = resIds
        .slice(0, limit)
        .filter((id) => !deleted.has(id))
        .map((id) => SERVER_ROWS[id]);
    const list = new StaticList(model, config, /** @type {any} */ (data), {
        parent,
        onUpdate: async () => {},
    });
    list.model._patchConfig(list.config, { resIds });
    list._currentIds = [...resIds];
    return list;
}

describe("count follows membership through a partial load", () => {
    test("_load drops a vanished id from count, not just from _currentIds", async () => {
        const list = makeList({
            resIds: [1, 2, 3, 99],
            limit: 2,
            deleted: new Set([99]),
        });

        await list._load({ offset: 2 });

        expect(list._currentIds).toEqual([1, 2, 3]);
        expect(list.count).toBe(3);
    });

    test("sort drops a vanished id from count too", async () => {
        const list = makeList({
            resIds: [1, 2, 3, 99],
            limit: 2,
            deleted: new Set([99]),
        });

        await sort(list, list._currentIds, [{ name: "display_name", asc: true }]);

        expect(list._currentIds).toEqual([2, 3, 1]);
        expect(list.count).toBe(3);
    });

    test("a growing load (_addRecord under an orderBy) grows count with it", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 10 });

        await list._load({ nextCurrentIds: [1, 2, 3, 99] });

        expect(list._currentIds).toEqual([1, 2, 3, 99]);
        expect(list.count).toBe(4);
    });

    test("departures are a MULTISET difference, not a set difference", async () => {
        const list = makeList({ resIds: [1, 2], limit: 10 });
        list._currentIds = [1, 1, 2];

        await list._load({ nextCurrentIds: [1, 2] });

        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);
    });
});

describe("removedIds counts removals rather than flagging them", () => {
    test("CLEAR then a repeated LINK of the same id adds it once", async () => {
        const list = makeList({ resIds: [1, 2] });

        await applyCommands(/** @type {any} */ (list), [
            [CLEAR, false, false],
            [LINK, 1, false],
            [LINK, 1, false],
        ]);

        expect(list._currentIds).toEqual([1]);
        expect(list.count).toBe(1);
        expect(list.records.map((r) => r.resId)).toEqual([1]);
        expect(readable(list._commands)).toEqual(["CLEAR:false", "LINK:1"]);
    });

    test("CLEAR then LINK then UNLINK of the same id leaves nothing behind", async () => {
        const list = makeList({ resIds: [1, 2, 3] });
        await list._replaceWith([1, 2, 3]);

        await applyCommands(/** @type {any} */ (list), [
            [CLEAR, false, false],
            [LINK, 1, false],
            [UPDATE, 1, { display_name: "edited" }],
            [UNLINK, 1, false],
        ]);

        expect(list._currentIds).toEqual([]);
        expect(list.count).toBe(0);
        expect(readable(list._commands)).toEqual(["CLEAR:false"]);
    });
});

describe("an UNLINK cancelling a re-LINK keeps the original UNLINK", () => {
    test("unlink a server member", async () => {
        const list = makeList({ resIds: [1, 2] });

        await list._applyCommands([[UNLINK, 1, false]]);

        expect(readable(list._commands)).toEqual(["UNLINK:1"]);
        expect(list._currentIds).toEqual([2]);
    });

    test("unlink then relink nets back to linked", async () => {
        const list = makeList({ resIds: [1, 2] });

        await list._applyCommands([[UNLINK, 1, false]]);
        await list._applyCommands([[LINK, 1, false]]);

        expect(readable(list._commands)).toEqual(["UNLINK:1", "LINK:1"]);
        expect(list._currentIds).toEqual([2, 1]);
        expect(list.count).toBe(2);
    });

    test("unlink, relink, unlink must still ship an UNLINK", async () => {
        const list = makeList({ resIds: [1, 2] });

        await list._applyCommands([[UNLINK, 1, false]]);
        await list._applyCommands([[LINK, 1, false]]);
        await list._applyCommands([[UNLINK, 1, false]]);

        expect(readable(list._commands)).toEqual(["UNLINK:1"]);
        expect(list._currentIds).toEqual([2]);
        expect(list.count).toBe(1);
    });

    test("link then unlink of a non-member still cancels out entirely", async () => {
        const list = makeList({ resIds: [2] });

        await list._applyCommands([[LINK, 1, false]]);
        await list._applyCommands([[UNLINK, 1, false]]);

        expect(readable(list._commands)).toEqual([]);
        expect(list._currentIds).toEqual([2]);
    });

    test("delete, relink, delete keeps shipping a DELETE", async () => {
        const list = makeList({ resIds: [1, 2] });

        await list._applyCommands([[DELETE, 1, false]]);
        await list._applyCommands([[LINK, 1, false]]);
        await list._applyCommands([[DELETE, 1, false]]);

        expect(readable(list._commands)).toEqual(["DELETE:1"]);
        expect(list._currentIds).toEqual([2]);
    });
});
