// @ts-check

/**
 * A bare ``LINK id`` command (no inlined values) queues the record for a
 * webRead. When that record is already in the list's cache with every active
 * field loaded there is nothing to fetch — ``_getResIdsToLoad`` is the
 * existing answer to "does this still need loading?" and the LINK branch has
 * to ask it, like the page-refill branch below it already does.
 *
 * This matters for SET, which ``expandSetCommands`` rewrites into
 * CLEAR + one LINK per id: re-applying a SET over an untouched page currently
 * re-reads the whole page.
 */

import { describe, expect, test } from "@odoo/hoot";
import { applyCommands } from "@web/model/relational_model/static_list_command_engine";

describe.current.tags("headless");

const LINK = 4;
const SET = 6;

/** @returns {any} a partial StaticList, enough for applyCommands */
function makeList() {
    /** @type {any[]} */
    const loadedIds = [];
    const list = /** @type {any} */ ({
        _commands: [],
        records: [],
        _currentIds: [],
        _cache: {},
        _unknownRecordCommands: {},
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
            list._cache[data.id] = record;
            return record;
        },
        _getResIdsToLoad: (/** @type {any} */ ids) =>
            ids.filter((/** @type {any} */ id) => !list._cache[id]?.complete),
        _bumpLimit() {},
        _clampOffset() {},
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

/** Seed the list with two fully-loaded records. */
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
        list.records = [list._cache[1]];
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
