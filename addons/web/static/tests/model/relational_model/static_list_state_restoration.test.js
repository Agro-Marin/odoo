// @ts-check

/**
 * ``StaticList``'s restorable state is declared once (``RESTORABLE_STATE`` +
 * ``RESTORABLE_CONFIG_KEYS``) and both ``_snapshot`` and ``_restore`` derive
 * from it, so the two can no longer describe different field sets.
 *
 * Pinned here:
 *  - the page window (``limit``/``offset``) round-trips through a snapshot —
 *    ``offset`` is rewritten by the page-anchor shift in ``applyCommands`` and
 *    by ``_clampOffset``, and used to be left behind by a restore;
 *  - ``_pruneCache`` never evicts a datapoint a STAGED command still names. A
 *    CREATE's row exists only in the cache — there is no server to re-read it
 *    from — so evicting it made ``serializeCommands`` hit its ``if (!record)
 *    continue`` and drop the row from the save payload without a word;
 *  - ``_replaceWith`` leaves ``records`` equal to the page window.
 *
 * DOM-free: the list is built on the real ``StaticList`` prototype, as in
 * static_list_pending_commands.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { x2ManyCommands } from "@web/core/network/commands";
import { ListMembership } from "@web/model/relational_model/list_membership";
import { StaticList } from "@web/model/relational_model/static_list";

const { CREATE } = x2ManyCommands;

/**
 * @param {Object} [opts]
 * @param {number[]} [opts.resIds]
 * @param {number} [opts.limit]
 * @param {number} [opts.offset]
 * @returns {any}
 */
function makeList({ resIds = [], limit = 40, offset = 0 } = {}) {
    const list = Object.create(StaticList.prototype);
    Object.assign(list, {
        // Membership owner first: the keys below write through its accessors.
        _membership: new ListMembership(),
        id: "datapoint_test",
        _config: {
            limit,
            offset,
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
                _changes: {},
                dirty: false,
                _loadedFieldNames: new Set(Object.keys(data)),
                _getChanges: () => ({}),
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

describe("snapshot / restore", () => {
    test("the page window round-trips", () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 1, offset: 1 });
        const snapshot = list._snapshot();

        list.model._patchConfig(list.config, { limit: 5, offset: 0 });
        list._restore(snapshot);

        expect(list.limit).toBe(1);
        expect(list.offset).toBe(1);
        expect(list.records.map((r) => r.resId)).toEqual([2]);
    });

    test("a restore reinstates the whole declared field set", () => {
        const list = makeList({ resIds: [1, 2] });
        list._unknownRecordCommands = { 9: [[1, 9, { display_name: "x" }]] };
        list._loadingStubIds.add(9);
        list._tmpIncreaseLimit = 2;
        const snapshot = list._snapshot();

        list._unknownRecordCommands = {};
        list._loadingStubIds.clear();
        list._tmpIncreaseLimit = 0;
        list._currentIds = [];
        list._restore(snapshot);

        expect(list._unknownRecordCommands).toEqual({
            9: [[1, 9, { display_name: "x" }]],
        });
        expect([...list._loadingStubIds]).toEqual([9]);
        expect(list._tmpIncreaseLimit).toBe(2);
        expect(list._currentIds).toEqual([1, 2]);
        expect(list.count).toBe(2);
    });
});

describe("_pruneCache", () => {
    test("keeps a datapoint a staged CREATE still names", () => {
        const list = makeList({ resIds: [1] });
        list._createRecordDatapoint({}, { virtualId: "virtual_1" });
        list._commands.push([CREATE, "virtual_1"]);
        // the id has left the membership (what `_replaceWith` produces) but the
        // command is still staged
        list._currentIds = [1];

        list._pruneCache();

        expect(list._cache["virtual_1"]).not.toBe(undefined);
    });

    test("still evicts a datapoint nothing references", () => {
        const list = makeList({ resIds: [1, 2] });
        list._currentIds = [1];
        list.model._patchConfig(list.config, { resIds: [1] });

        list._pruneCache();

        expect(list._cache[2]).toBe(undefined);
        expect(list._cache[1]).not.toBe(undefined);
    });
});

describe("_replaceWith", () => {
    test("leaves records equal to the page window and lands on page 1", async () => {
        const list = makeList({ resIds: [1, 2, 3], limit: 1, offset: 1 });

        await list._replaceWith([1, 2, 3]);

        expect(list.offset).toBe(0);
        expect(list.records.map((r) => r.resId)).toEqual(
            list.currentIds.slice(list.offset, list.offset + list.limit),
        );
    });
});
