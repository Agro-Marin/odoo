// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { applyCommands } from "@web/model/relational_model/static_list_command_engine";

describe.current.tags("headless");

const LINK = 4;
const SET = 6;

/** @returns {any} */
function makeList() {
    /** @type {any[]} */
    const loadedIds = [];
    const list = /** @type {any} */ ({
        _commands: [],
        records: [],
        _currentIds: [],
        _cache: new Map(),
        _unknownRecordCommands: new Map(),
        _loadingStubIds: new Set(),
        offset: 0,
        limit: 80,
        count: 0,
        config: {},
        fields: {},
        resModel: "line",
        evalContext: {},
        loadedIds,
        _createRecordDatapoint(/** @type {any} */ data) {
            const record = {
                resId: data.id || false,
                _virtualId: false,
                activeFields: {},
                data: { ...data },
                complete: Boolean(data.name),
                _applyValues(/** @type {any} */ values) {
                    Object.assign(this.data, values);
                    this.complete = true;
                },
                _applyChanges() {},
            };
            list._cache.set(data.id, record);
            return record;
        },
        _getResIdsToLoad: (/** @type {any} */ ids) =>
            ids.filter((/** @type {any} */ id) => !list._cache.get(id)?.complete),
        _bumpLimit() {},
        _clampOffset() {},
        _commitCommands(/** @type {any[]} */ commands) {
            this._commands = commands;
        },
        _commitCurrentIds(/** @type {any[]} */ ids) {
            this._currentIds = ids;
        },
        _insertMemberAt(/** @type {number} */ index, /** @type {any} */ id) {
            this._currentIds.splice(index, 0, id);
        },
        _appendMember(/** @type {any} */ id) {
            this._currentIds.push(id);
        },
        model: {
            _patchConfig: () => {},
            _loadRecords: (/** @type {any} */ { resIds }) => {
                loadedIds.push(...resIds);
                return Promise.resolve(
                    resIds.map((/** @type {any} */ id) => ({ id, name: `n${id}` })),
                );
            },
        },
    });
    return list;
}

function seed(/** @type {any} */ list) {
    for (const id of [1, 2]) {
        const record = list._createRecordDatapoint({ id, name: `n${id}` });
        list.records.push(record);
        list._currentIds.push(id);
        list.count++;
    }
}

describe("LINK of an already-loaded record", () => {
    test("does not re-read a cached, complete record", async () => {
        const list = makeList();
        seed(list);
        list._currentIds = [1];
        list.records = [list._cache.get(1)];
        list.count = 1;

        await applyCommands(list, [[LINK, 2, false]]);

        expect(list.loadedIds).toEqual([]);
        expect(list._currentIds).toEqual([1, 2]);
    });

    test("still reads a record that is not cached", async () => {
        const list = makeList();
        seed(list);

        await applyCommands(list, [[LINK, 7, false]]);

        expect(list.loadedIds).toEqual([7]);
    });

    test("re-applying a SET over an untouched page reads nothing", async () => {
        const list = makeList();
        seed(list);

        await applyCommands(list, [[SET, false, [1, 2]]]);

        expect(list.loadedIds).toEqual([]);
        expect(list._currentIds).toEqual([1, 2]);
    });
});
