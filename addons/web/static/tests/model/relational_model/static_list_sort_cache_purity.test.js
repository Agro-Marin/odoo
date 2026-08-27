// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";
import { sortStaticList } from "@web/model/relational_model/static_list_sort";

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

describe("sortStaticList() keeps _cache free of narrowly-specified datapoints", () => {
    test("an off-page row read only for its sort key does not become a datapoint", async () => {
        const { list } = makeList();

        await sortStaticList(list, list._currentIds, [{ name: "name", asc: true }]);

        for (const [id, record] of /** @type {any} */ (list._cache)) {
            expect(Object.keys(record.activeFields).sort()).toEqual(["name", "note"], {
                message: `datapoint ${id} must declare the list's fields`,
            });
        }
        expect([.../** @type {any} */ (list._cache).keys()].map(Number).sort()).toEqual(
            [1, 2, 5, 6],
        );
    });

    test("a list whose fields the sort already covers still sorts in one request", async () => {
        const { list, requested } = makeList({ fieldNames: ["name"] });

        await sortStaticList(list, list._currentIds, [{ name: "name", asc: true }]);

        expect(requested).toEqual([{ ids: [3, 4, 5, 6], spec: ["name"] }]);
        expect(list.records.map((r) => r.data.name)).toEqual(["A", "B"]);
    });

    test("a cached row is refreshed in place, not replaced", async () => {
        const { list } = makeList();
        const before = /** @type {any} */ (list._cache).get(1);
        before._changes.note = "PENDING";

        await sortStaticList(list, list._currentIds, [{ name: "name", asc: true }]);

        expect(/** @type {any} */ (list._cache).get(1)).toBe(before);
        expect(before._changes.note).toBe("PENDING");
    });

    test("ordering still uses the freshly read keys of off-page rows", async () => {
        const { list } = makeList();

        await sortStaticList(list, list._currentIds, [{ name: "name", asc: true }]);

        expect(list._currentIds).toEqual([6, 5, 4, 3, 2, 1]);
    });
});
