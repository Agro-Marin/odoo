// @ts-check

/**
 * Regression test for the partial-response hole in ``static_list_sort.sort()``.
 *
 * ``sort`` is the third loader in the x2many stack, next to
 * ``StaticList._load`` (static_list_partial_load.test.js) and
 * ``StaticList._replaceWith`` (static_list_replace_with_partial.test.js). Both
 * of those already drop ids the server no longer returns —
 * ``RelationalModel._loadRecords`` throws only when ZERO rows come back, so a
 * row unlinked server-side between the request and its load simply comes back
 * missing. ``sort`` had no such guard: it mapped every requested id through
 * ``_cache`` and then read ``.resId`` off the holes.
 *
 * The crash did not land in the comparator — ``Array.prototype.sort`` moves
 * ``undefined`` entries to the end WITHOUT invoking it — but on the
 * ``nextCurrentIds`` map right after, as ``Cannot read properties of undefined
 * (reading 'resId')``.
 *
 * The precondition is ordinary, not exotic: a paginated x2many caches only the
 * rows of the page it displays while ``_currentIds`` lists the whole relation,
 * so sorting always loads the off-page ids. Reachable by clicking a column
 * header in an editable x2many list, by drag-resequencing, and from
 * ``_addRecord`` under an ``orderBy``.
 *
 * Uses the REAL StaticList and RelationalRecord against a mock model, in the
 * style of static_list_partial_load.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";
import { sort } from "@web/model/relational_model/static_list_sort";

const SERVER_ROWS = {
    1: { id: 1, display_name: "C" },
    2: { id: 2, display_name: "A" },
    3: { id: 3, display_name: "B" },
    99: { id: 99, display_name: "Z" },
};

function makeList({ resIds = [], limit = 10, deleted = new Set() } = {}) {
    const requested = [];
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => {
            requested.push([...ids]);
            return ids.filter((id) => !deleted.has(id)).map((id) => SERVER_ROWS[id]);
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
    // Only the first page is materialised, exactly as the server sends it.
    const data = resIds
        .slice(0, limit)
        .filter((id) => !deleted.has(id))
        .map((id) => SERVER_ROWS[id]);
    const list = new StaticList(model, config, data, {
        parent,
        onUpdate: async () => {},
    });
    // ``_createStaticListDatapoint`` derives ``resIds`` from the whole server
    // value, so membership legitimately outruns the cache.
    list.model._patchConfig(list.config, { resIds });
    list._currentIds = [...resIds];
    return { list, requested };
}

describe("static_list_sort.sort partial server response", () => {
    test("an id the server no longer returns is dropped, not left as a hole", async () => {
        const { list, requested } = makeList({
            resIds: [1, 2, 3, 99],
            limit: 2,
            deleted: new Set([99]),
        });
        expect(list._currentIds.filter((id) => !list._cache[id])).toEqual([3, 99]);

        await sort(list, list._currentIds, [{ name: "display_name", asc: true }]);

        expect(requested).toEqual([[3, 99]]);
        expect(list.records.includes(undefined)).toBe(false);
        expect(list._currentIds).toEqual([2, 3, 1]);
        expect(list.records.map((r) => r.data.display_name)).toEqual(["A", "B"]);
    });

    test("a full response still keeps every id (guard is inert on the happy path)", async () => {
        const { list } = makeList({ resIds: [1, 2, 3, 99], limit: 2 });

        await sort(list, list._currentIds, [{ name: "display_name", asc: true }]);

        expect(list._currentIds).toEqual([2, 3, 1, 99]);
        expect(list.records.map((r) => r.data.display_name)).toEqual(["A", "B"]);
    });
});
