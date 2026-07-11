// @ts-check

/**
 * Regression tests for the LINK-over-full-page stub bug: a LINK command
 * without server data applied while the page is full caches a stub datapoint
 * built from a bare ``{id}`` but never loads it (the load sits inside the
 * under-limit branch). ``_getResIdsToLoad`` must classify that stub as NOT
 * loaded — it tests ``record._loadedFieldNames`` (values actually fetched),
 * not ``record.fieldNames`` (the view's full activeFields, complete even on
 * a stub) — so the next page navigation fetches real values instead of
 * rendering a row of defaults.
 *
 * Uses the REAL StaticList and RelationalRecord classes against a mock model,
 * in the style of static_list_pending_commands.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const LINK = 4;

const SERVER_ROWS = {
    1: { id: 1, display_name: "Rec 1" },
    2: { id: 2, display_name: "Rec 2" },
    3: { id: 3, display_name: "Rec 3" },
    99: { id: 99, display_name: "Rec 99" },
};

function makeList({ resIds = [], limit = 2 } = {}) {
    const loadedResIds = [];
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => {
            loadedResIds.push([...ids]);
            return ids.map((id) => SERVER_ROWS[id]);
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
    const data = resIds.map((id) => SERVER_ROWS[id]);
    const list = new StaticList(model, config, data, {
        parent,
        onUpdate: async () => {},
    });
    return { list, loadedResIds };
}

describe("LINK on a full page", () => {
    test("the linked record is loaded on page navigation, not mapped as a stub", async () => {
        const { list, loadedResIds } = makeList({ resIds: [1, 2, 3], limit: 2 });
        expect(list.records.map((r) => r.resId)).toEqual([1, 2]);

        // LINK without server data (e.g. linkTo() after an m2m dialog save,
        // or a server onchange [4, id] command) while the page is full.
        await list._applyCommands([[LINK, 99, false]]);

        expect(list._currentIds).toEqual([1, 2, 3, 99]);
        expect(list.count).toBe(4);
        // The stub was cached but not displayed/loaded (page full).
        expect(list.records.map((r) => r.resId)).toEqual([1, 2]);
        expect(loadedResIds).toEqual([]);

        // Navigate to the second page: the stub must be fetched along with
        // the never-loaded record 3.
        await list._load({ offset: 2 });

        expect(loadedResIds).toEqual([[3, 99]]);
        expect(list.records.map((r) => r.resId)).toEqual([3, 99]);
        expect(list.records[0].data.display_name).toBe("Rec 3");
        // Without the _loadedFieldNames check this rendered the default
        // (blank) value: the stub's fieldNames derive from activeFields and
        // looked "already loaded".
        expect(list.records[1].data.display_name).toBe("Rec 99");
    });

    test("fully loaded cached records are not refetched on navigation", async () => {
        const { list, loadedResIds } = makeList({ resIds: [1, 2], limit: 2 });

        await list._load({ offset: 0 });

        // Both records came fully loaded from the constructor's data.
        expect(loadedResIds).toEqual([]);
        expect(list.records.map((r) => r.data.display_name)).toEqual([
            "Rec 1",
            "Rec 2",
        ]);
    });

    test("a LINK with server data on a full page needs no later load", async () => {
        const { list, loadedResIds } = makeList({ resIds: [1, 2], limit: 2 });

        await list._applyCommands([[LINK, 99, SERVER_ROWS[99]]]);
        await list._load({ offset: 2 });

        expect(loadedResIds).toEqual([]);
        expect(list.records.map((r) => r.resId)).toEqual([99]);
        expect(list.records[0].data.display_name).toBe("Rec 99");
    });
});
