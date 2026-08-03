// @ts-check

/**
 * Membership/ledger invariants of the x2many stack that no existing suite
 * pinned. Three holes, of clearly different severity:
 *
 *  1. ``count`` drifting away from ``_currentIds`` when a loader drops ids the
 *     server no longer returns. ``StaticList._load`` and ``static_list_sort.sort``
 *     both already trim membership (see static_list_partial_load.test.js and
 *     static_list_sort_partial_load.test.js) but used to leave ``count``
 *     untouched. On a ``StaticList`` ``count`` has exactly one consumer —
 *     ``x2many_field``'s ``pagerProps.total`` — so the symptom is a page total
 *     that outruns the rows. It does NOT reach ``findUnsetRequiredFields``:
 *     that tests ``!list.count``, and a load in which *every* id vanishes
 *     throws ``FetchRecordError`` before the trim, so a phantom count is never
 *     the difference between zero and non-zero.
 *
 *  2. ``removedIds`` was a boolean flag but drives a *positional* drop
 *     (``dropFirstOccurrences``). CLEAR-then-LINK-then-UNLINK marks one id
 *     twice and must drop two entries; one flag could only ever drop one, so
 *     the unlinked row survived in ``_currentIds``. No caller is known to emit
 *     such a batch today: this pins the invariant, it does not fix a live bug.
 *
 *  3. ``shouldEmitUnlink`` cancelled a LINK by clearing the id's whole ledger.
 *     When an UNLINK *preceded* that LINK — the row was a server member the
 *     user removed, restored, then removed again — the original UNLINK went
 *     with it. The record then read as clean, so ``web_save`` was never called
 *     at all: the UI dropped the row, the server kept it, and nothing was
 *     flagged dirty. Reachable in a ``many2many_tags`` field in three
 *     interactions (end-to-end proof in
 *     tests/views/fields/many2many_tags_field.test.js). The one2many *widget*
 *     path is unaffected -- it removes rows with DELETE, via
 *     ``shouldEmitDelete`` -- though a one2many can still carry UNLINK if a
 *     server onchange emits command 3.
 */

import { describe, expect, test } from "@odoo/hoot";
import { x2ManyCommands } from "@web/model/relational_model/commands";
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
 * A StaticList over hand-rolled model/config/parent skeletons — enough of each
 * for the membership paths under test, deliberately not the real objects. The
 * defaults are typed because a bare `[]` infers `never[]`, which rejects every
 * caller's id list.
 *
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
    // Only the first page is materialised, exactly as the server sends it;
    // membership legitimately outruns the cache on a paginated x2many.
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
        // `_addRecord` under an orderBy reaches `_load` through `sort()` with
        // the new id already in `nextCurrentIds`. `count` is derived, so it
        // grows the moment the id list does -- there is no window in which the
        // list holds N+1 members and reports N, which is what the old
        // count-follows-by-hand protocol left open between here and
        // `_addRecord`'s own increment.
        const list = makeList({ resIds: [1, 2, 3], limit: 10 });

        await list._load({ nextCurrentIds: [1, 2, 3, 99] });

        expect(list._currentIds).toEqual([1, 2, 3, 99]);
        expect(list.count).toBe(4);
    });

    test("departures are a MULTISET difference, not a set difference", async () => {
        // Membership held twice used to need a MULTISET difference to count
        // departures: an id present twice that comes back once is one
        // departure, not zero, and a set-based `!next.has(id)` reported zero.
        // Deriving `count` from the id list removes the question entirely --
        // kept as a regression test because the duplicate-membership state it
        // exercises is still reachable.
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

        await applyCommands(list, [
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

        await applyCommands(list, [
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
