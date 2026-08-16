// @ts-check

/**
 * A ``SET`` command reaches a StaticList by two routes, and they are NOT
 * interchangeable:
 *
 *  - **client-authored** (``record.update({field: [[6, false, ids]]})``) —
 *    ``preprocessX2manyChanges`` intercepts it and calls ``_replaceWith``;
 *  - **server-authored** (an onchange payload, reaching ``_applyCommands``) —
 *    ``expandSetCommands`` rewrites it as ``CLEAR`` + one ``LINK`` per id.
 *
 * These tests pin the difference so it cannot drift silently. See the
 * cross-referenced comments on ``StaticList._replaceWith`` and
 * ``expandSetCommands``.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network/commands";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

const { UPDATE, SET, CLEAR, LINK } = x2ManyCommands;

/** @param {number[]} resIds */
function makeList(resIds) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        // Membership owner first: the keys below write through its accessors.
        _membership: new ListMembership(),
        id: "datapoint_test",
        _config: {
            limit: 40,
            offset: 0,
            resIds: [...resIds],
            orderBy: [],
            resModel: "res.partner",
            context: {},
            activeFields: { display_name: {} },
            fields: { display_name: { type: "char" } },
        },
        records: [],
        _cache: markRaw({}),
        _commands: [],
        _initialCommands: [],
        _commandsPromise: null,
        _savePoint: undefined,
        _unknownRecordCommands: {},
        _loadingStubIds: new Set(),
        _currentIds: [...resIds],
        _tmpIncreaseLimit: 0,
        _extendedRecords: new Set(),
        model: {
            _patchConfig: (config, patch) => Object.assign(config, patch),
            _loadRecords: async (config) => config.resIds.map((id) => ({ id })),
        },
        _createRecordDatapoint(data, params = {}) {
            const id = data.id || params.virtualId;
            const record = {
                id: `dp_${id}`,
                resId: data.id || false,
                _virtualId: params.virtualId || false,
                data: { ...data },
                _changes: { display_name: "edited" },
                dirty: true,
                _loadedFieldNames: new Set(Object.keys(data)),
                _getChanges: () => ({ display_name: "edited" }),
                _applyChanges() {},
                _applyValues() {},
            };
            this._cache[id] = record;
            return record;
        },
    });
    for (const resId of resIds) {
        list._createRecordDatapoint({ id: resId });
        list.records.push(list._cache[resId]);
    }
    return list;
}

describe("client-authored SET (_replaceWith)", () => {
    test("emits a SET and KEEPS a staged edit on a surviving row", async () => {
        const list = makeList([1, 2, 3]);
        list._commands.push([UPDATE, 1]);

        await list._replaceWith([1, 2]);

        expect(list._commands[0][0]).toBe(SET);
        expect(list._commands[0][2]).toEqual([1, 2]);
        const serialized = list._getCommands();
        const update = serialized.find((c) => c[0] === UPDATE && c[1] === 1);
        expect(update).not.toBe(undefined);
        expect(update[2]).toEqual({ display_name: "edited" });
    });

    test("drops a staged edit on a row the SET excludes", async () => {
        const list = makeList([1, 2, 3]);
        list._commands.push([UPDATE, 3]);

        await list._replaceWith([1, 2]);

        expect(list._getCommands().some((c) => c[0] === UPDATE && c[1] === 3)).toBe(
            false,
        );
    });
});

describe("server-authored SET (expandSetCommands)", () => {
    test("expands to CLEAR + LINK and DISCARDS staged edits", async () => {
        const list = makeList([1, 2, 3]);
        list._commands.push([UPDATE, 1]);

        await list._applyCommands([[SET, false, [1, 2]]]);

        expect(list._commands.map((c) => c[0])).toEqual([CLEAR, LINK, LINK]);
        expect(list._getCommands().some((c) => c[0] === UPDATE)).toBe(false);
        expect(list._currentIds).toEqual([1, 2]);
    });

    test("omits the CLEAR when there was nothing to reset", async () => {
        const list = makeList([]);

        await list._applyCommands([[SET, false, [1, 2]]]);

        expect(list._commands.map((c) => c[0])).toEqual([LINK, LINK]);
    });
});

describe("both routes agree on membership", () => {
    test("same resulting currentIds and count", async () => {
        const viaReplaceWith = makeList([1, 2, 3]);
        await viaReplaceWith._replaceWith([2, 3]);

        const viaExpandSet = makeList([1, 2, 3]);
        await viaExpandSet._applyCommands([[SET, false, [2, 3]]]);

        expect(viaReplaceWith._currentIds).toEqual(viaExpandSet._currentIds);
        expect(viaReplaceWith.count).toBe(viaExpandSet.count);
    });
});
