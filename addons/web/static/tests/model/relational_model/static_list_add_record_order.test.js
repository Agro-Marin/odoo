// @ts-check

/**
 * Unit test for StaticList._addRecord(position:"top") command ordering.
 *
 * A top-position add must insert its CREATE command AFTER any leading
 * SET/CLEAR (from _replaceWith), not at index 0. The server applies commands
 * in order: a CREATE before a SET is created and then dropped when the SET
 * replaces the whole relation. Built on the real StaticList.prototype with a
 * minimal state object (the "top" branch touches no async / sort paths).
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/model/relational_model/commands";
import { StaticList } from "@web/model/relational_model/static_list";

function makeSortableList() {
    const rec1 = { resId: 1, data: { name: "b" } };
    const rec2 = { resId: 2, data: { name: "c" } };
    const recV = { resId: false, _virtualId: "v", data: { name: "a" } };
    return {
        records: [rec1, rec2],
        _cache: { 1: rec1, 2: rec2, v: recV },
        _currentIds: [1, 2],
        _commands: [],
        limit: 40,
        offset: 0,
        count: 2,
        orderBy: [{ name: "name", asc: true }],
        fields: { name: { type: "char" } },
        model: { _patchConfig() {} },
        config: {},
        // All values already cached => sort() loads nothing.
        _getResIdsToLoad: () => [],
        // Use the real _load so we exercise its ``this._currentIds = nextCurrentIds``.
        _load: StaticList.prototype._load,
    };
}

function makeList(commands) {
    return {
        records: [],
        _currentIds: [1, 2],
        _commands: commands,
        limit: 40,
        offset: 0,
        count: 2,
    };
}

describe("StaticList._addRecord(top) command ordering", () => {
    test("inserts CREATE AFTER a leading SET so the new row survives", async () => {
        const list = makeList([[x2ManyCommands.SET, false, [1, 2]]]);

        await StaticList.prototype._addRecord.call(
            list,
            { _virtualId: "virt-1" },
            { position: "top" },
        );

        expect(list._commands).toEqual([
            [x2ManyCommands.SET, false, [1, 2]],
            [x2ManyCommands.CREATE, "virt-1"],
        ]);
        expect(list.records[0]).toEqual({ _virtualId: "virt-1" });
    });

    test("with no SET/CLEAR, CREATE stays at the front (unchanged behaviour)", async () => {
        const list = makeList([[x2ManyCommands.UPDATE, 5, {}]]);

        await StaticList.prototype._addRecord.call(
            list,
            { _virtualId: "virt-2" },
            { position: "top" },
        );

        expect(list._commands).toEqual([
            [x2ManyCommands.CREATE, "virt-2"],
            [x2ManyCommands.UPDATE, 5, {}],
        ]);
    });

    test("default add on a sorted list keeps _currentIds in the sorted order", async () => {
        const list = makeSortableList();
        const recV = list._cache.v;

        // Default position (no position) with orderBy set => sort branch.
        await StaticList.prototype._addRecord.call(list, recV);

        // sortRecords committed the sorted order (a, b, c) => ["v", 1, 2];
        // _addRecord must NOT clobber it back to insertion order [1, 2, "v"].
        expect(list._currentIds).toEqual(["v", 1, 2]);
        expect(list.records.map((r) => r.data.name)).toEqual(["a", "b", "c"]);
        expect(list._commands).toEqual([[x2ManyCommands.CREATE, "v"]]);
    });

    test("inserts after BOTH a leading CLEAR and SET", async () => {
        const list = makeList([
            [x2ManyCommands.CLEAR, false, false],
            [x2ManyCommands.SET, false, [1, 2]],
        ]);

        await StaticList.prototype._addRecord.call(
            list,
            { _virtualId: "virt-3" },
            { position: "top" },
        );

        expect(list._commands[2]).toEqual([x2ManyCommands.CREATE, "virt-3"]);
    });
});
