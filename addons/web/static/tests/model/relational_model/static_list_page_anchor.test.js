// @ts-check

/**
 * Regression tests for the page-anchor bug in ``applyCommands``.
 *
 * Sibling of static_list_offset_clamp.test.js, which covers the case
 * ``_clampOffset`` DOES catch: a batch removing every id at or after the page
 * start leaves ``offset`` past the end, so the window resolves to an empty
 * slice. This file covers the case it cannot catch — rows removed from BEFORE
 * the page start.
 *
 * There ``offset`` stays in range, so ``_clampOffset`` returns early, but the
 * whole membership has slid one index per removed row. ``records`` still holds
 * the right rows (the removal filter only drops the removed ones) while
 * ``_currentIds.slice(offset, offset + limit)`` now names entirely different
 * ids: the pager counted one page while another rendered, and the next
 * ``_load`` — which rebuilds ``records`` FROM that window — teleported the user
 * to rows they never asked for.
 *
 * Re-anchoring ``offset`` by the number of rows removed ahead of it keeps the
 * user on exactly the rows they were looking at, which is also what makes the
 * subsequent page-fill pass reason about the page actually on screen.
 *
 * Uses the REAL StaticList and RelationalRecord against a mock model, in the
 * style of static_list_offset_clamp.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { makeActiveField } from "@web/model/relational_model/field_metadata";
import { RelationalRecord } from "@web/model/relational_model/record";
import { StaticList } from "@web/model/relational_model/static_list";

const UNLINK = 3;

/** @type {Record<number, { id: number, display_name: string }>} */
const SERVER_ROWS = {};
for (let id = 1; id <= 8; id++) {
    SERVER_ROWS[id] = { id, display_name: `Rec ${id}` };
}

function makeList({ resIds = [], limit = 3 } = {}) {
    const model = {
        Class: { Record: RelationalRecord, StaticList },
        _patchConfig: (config, patch) => Object.assign(config, patch),
        _loadRecords: async ({ resIds: ids }) => ids.map((id) => SERVER_ROWS[id]),
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
    return new StaticList(model, config, data, {
        parent,
        onUpdate: async () => {},
    });
}

/** The rows on screen must be the ids the window names. */
function expectWindowMatchesRecords(list) {
    expect(list.records.map((r) => r.resId)).toEqual(
        list._currentIds.slice(list.offset, list.offset + list.limit),
    );
}

describe("page anchor after rows are removed ahead of the offset", () => {
    test("unlinking earlier-page rows keeps the user on the same records", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5, 6, 7], limit: 3 });
        await list._load({ offset: 3 });
        expect(list.records.map((r) => r.resId)).toEqual([4, 5, 6]);

        // Rows 1-3 live on page 1; the user is on page 2.
        await list._applyCommands([
            [UNLINK, 1, false],
            [UNLINK, 2, false],
            [UNLINK, 3, false],
        ]);

        expect(list._currentIds).toEqual([4, 5, 6, 7]);
        expect(list.count).toBe(4);
        expect(list.offset).toBe(0);
        expect(list.records.map((r) => r.resId)).toEqual([4, 5, 6]);
        expectWindowMatchesRecords(list);
    });

    test("a partial shift re-anchors by exactly the number removed ahead", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5, 6, 7], limit: 3 });
        await list._load({ offset: 3 });

        await list._applyCommands([[UNLINK, 2, false]]);

        expect(list._currentIds).toEqual([1, 3, 4, 5, 6, 7]);
        expect(list.offset).toBe(2);
        expect(list.records.map((r) => r.resId)).toEqual([4, 5, 6]);
        expectWindowMatchesRecords(list);
    });

    test("a removal on the CURRENT page does not move the anchor", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5, 6, 7], limit: 3 });
        await list._load({ offset: 3 });

        await list._applyCommands([[UNLINK, 5, false]]);

        expect(list.offset).toBe(3);
        expect(list._currentIds).toEqual([1, 2, 3, 4, 6, 7]);
        expectWindowMatchesRecords(list);
    });

    test("a later _load lands on the rows the user was shown", async () => {
        const list = makeList({ resIds: [1, 2, 3, 4, 5, 6, 7], limit: 3 });
        await list._load({ offset: 3 });
        await list._applyCommands([
            [UNLINK, 1, false],
            [UNLINK, 2, false],
        ]);
        const onScreen = list.records.map((r) => r.resId);

        await list._load({});

        expect(list.records.map((r) => r.resId)).toEqual(onScreen);
    });
});
