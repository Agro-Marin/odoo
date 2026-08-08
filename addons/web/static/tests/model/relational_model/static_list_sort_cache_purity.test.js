// @ts-check

/**
 * ``sort()`` has to read the sort columns of rows that are NOT on the current
 * page, because ordering the relation needs every member's key. It reads them
 * narrowly -- ``pick(activeFields, ...orderByFieldNames)`` -- and used to turn
 * each narrow response into a datapoint via
 * ``_createRecordDatapoint(record, { activeFields })``.
 *
 * That put records into ``_cache`` whose ``config.activeFields`` was a strict
 * subset of the list's. ``_cache`` is walked by the save path
 * (``x2many_tree.js``), by ``record_validator``'s child check, and by
 * ``extendRecord``; all of them read ``record.activeFields`` and
 * ``record.data`` and none of them expect a member of the list to declare
 * different fields from the list itself.
 *
 * The narrow read now produces a throwaway sort key instead. Two exceptions
 * keep the round-trip count where it was:
 *   - an id already in ``_cache`` is REFRESHED in place, so the fresh sort
 *     column reaches the comparator without discarding pending edits;
 *   - a read that happens to cover the list's whole field set is promoted to a
 *     real datapoint, so a single-field list still sorts in one request.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";
import { sort } from "@web/model/relational_model/static_list_sort";

const ROWS = {
    1: { id: 1, name: "F", note: "n1" },
    2: { id: 2, name: "E", note: "n2" },
    3: { id: 3, name: "D", note: "n3" },
    4: { id: 4, name: "C", note: "n4" },
    5: { id: 5, name: "B", note: "n5" },
    6: { id: 6, name: "A", note: "n6" },
};

/**
 * @param {Object} [opts]
 * @param {number[]} [opts.resIds]
 * @param {number} [opts.limit]
 * @param {string[]} [opts.fieldNames]
 */
function makeList({
    resIds = [1, 2, 3, 4, 5, 6],
    limit = 2,
    fieldNames = ["name", "note"],
} = {}) {
    /** @type {{ ids: any[], spec: string[] }[]} */
    const requested = [];
    /** @type {Record<string, any>} */
    const activeFields = {};
    /** @type {Record<string, any>} */
    const fields = {};
    for (const name of fieldNames) {
        activeFields[name] = makeActiveField();
        fields[name] = { type: "char", name };
    }
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (/** @type {any} */ config, /** @type {any} */ patch) =>
            Object.assign(config, patch),
        _loadRecords: async (/** @type {any} */ { resIds: ids, activeFields: af }) => {
            requested.push({ ids: [...ids], spec: Object.keys(af).sort() });
            return ids.map((/** @type {number} */ id) => {
                /** @type {Record<string, any>} */
                const row = { id };
                for (const name of Object.keys(af)) {
                    row[name] = /** @type {Record<number, any>} */ (ROWS)[id][name];
                }
                return row;
            });
        },
    };
    const config = {
        resModel: "line",
        activeFields,
        fields,
        relationField: false,
        offset: 0,
        limit,
        resIds,
        orderBy: /** @type {any[]} */ ([]),
        context: {},
    };
    const list = new StaticList(
        /** @type {any} */ (model),
        /** @type {any} */ (config),
        resIds.slice(0, limit).map((/** @type {number} */ id) => ({
            .../** @type {Record<number, any>} */ (ROWS)[id],
        })),
        {
            parent: {
                evalContext: {},
                evalContextWithVirtualIds: {},
                _isEvalContextReady: true,
            },
            onUpdate: async () => {},
        },
    );
    list.model._patchConfig(list.config, { resIds });
    list._currentIds = [...resIds];
    return { list, requested };
}

describe("sort() keeps _cache free of narrowly-specified datapoints", () => {
    test("an off-page row read only for its sort key does not become a datapoint", async () => {
        const { list } = makeList();

        await sort(list, list._currentIds, [{ name: "name", asc: true }]);

        // Ascending by name (F,E,D,C,B,A) puts ids 6 and 5 on page 1, so they
        // are loaded in full alongside the originally-cached 1 and 2. Ids 3 and
        // 4 were read ONLY for their sort key and stay off page: they must be
        // absent from the cache rather than present with half a field set.
        for (const [id, record] of Object.entries(
            /** @type {Record<string, any>} */ (list._cache),
        )) {
            expect(Object.keys(record.activeFields).sort()).toEqual(["name", "note"], {
                message: `datapoint ${id} must declare the list's fields`,
            });
        }
        expect(
            Object.keys(/** @type {Record<string, any>} */ (list._cache))
                .map(Number)
                .sort(),
        ).toEqual([1, 2, 5, 6]);
    });

    test("a list whose fields the sort already covers still sorts in one request", async () => {
        const { list, requested } = makeList({ fieldNames: ["name"] });

        await sort(list, list._currentIds, [{ name: "name", asc: true }]);

        expect(requested).toEqual([{ ids: [3, 4, 5, 6], spec: ["name"] }]);
        expect(list.records.map((r) => r.data.name)).toEqual(["A", "B"]);
    });

    test("a cached row is refreshed in place, not replaced", async () => {
        const { list } = makeList();
        const before = /** @type {Record<string, any>} */ (list._cache)[1];
        before._changes.note = "PENDING";

        await sort(list, list._currentIds, [{ name: "name", asc: true }]);

        expect(/** @type {Record<string, any>} */ (list._cache)[1]).toBe(before);
        expect(before._changes.note).toBe("PENDING");
    });

    test("ordering still uses the freshly read keys of off-page rows", async () => {
        const { list } = makeList();

        await sort(list, list._currentIds, [{ name: "name", asc: true }]);

        // names are F,E,D,C,B,A for ids 1..6 -> ascending is 6,5,4,3,2,1
        expect(list._currentIds).toEqual([6, 5, 4, 3, 2, 1]);
    });
});
