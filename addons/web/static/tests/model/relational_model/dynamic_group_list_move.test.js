// @ts-check

/**
 * Unit tests for DynamicGroupList.moveRecord (dynamic_group_list.js).
 *
 * A cross-group move optimistically splices the datapoint into the target
 * group, then persists via ``record.update({ save: true })`` (whose own
 * ``mutex.exec`` serializes concurrent saves). On a failed save the move must
 * be reverted — and crucially the record's (unsaved) groupby-field change must
 * be DISCARDED, not just the datapoint moved back. Otherwise the reverted card
 * renders in its original column while still carrying the target column's value
 * with dirty=true.
 *
 * Uses ``Object.create(DynamicGroupList.prototype)`` with hand-built state,
 * mirroring the model suite's mock style.
 */

import { describe, expect, test } from "@odoo/hoot";
import { DynamicGroupList } from "@web/model/relational_model/dynamic_group_list";

const GROUPBY_FIELD = { type: "many2one", name: "stage_id", relation: "stage" };

function makeRec(id, steps, { updateResult = true, updateThrows = false } = {}) {
    const rec = {
        id,
        discarded: false,
        updateChanges: null,
        async update(changes) {
            steps.push(`${id}:update`);
            rec.updateChanges = changes;
            if (updateThrows) {
                throw new Error("save boom");
            }
            return updateResult;
        },
        _discard() {
            steps.push(`${id}:discard`);
            rec.discarded = true;
        },
    };
    return rec;
}

function makeGroup(id, value, records, steps) {
    return {
        id,
        value,
        displayName: `G-${id}`,
        isFolded: false,
        groupByField: GROUPBY_FIELD,
        list: {
            records,
            count: records.length,
            offset: 0,
            limit: 40,
            orderBy: [],
            domain: [],
            async _load() {
                steps.push(`${id}:load`);
            },
            async _resequence() {
                steps.push(`${id}:reseq`);
            },
        },
        _removeRecords() {
            steps.push(`${id}:remove`);
        },
        _addRecord() {
            steps.push(`${id}:add`);
        },
    };
}

function makeList(groups) {
    const list = Object.create(DynamicGroupList.prototype);
    Object.assign(list, {
        groups,
        // ``resModel`` is a DataPoint getter deriving from ``config`` — set it
        // through ``_config`` rather than assigning the read-only property.
        _config: { resModel: "task" },
        // The revert path serializes through the model mutex (it calls
        // record._discard, Invariant I4).
        model: { mutex: { exec: (fn) => Promise.resolve(fn()) } },
    });
    return list;
}

describe("moveRecord cross-group success", () => {
    test("persists the groupby change via update({save:true}) without discarding", async () => {
        const steps = [];
        const rA = makeRec("rA", steps, { updateResult: true });
        const g1 = makeGroup("g1", 1, [rA], steps);
        const g2 = makeGroup("g2", 2, [], steps);
        const list = makeList([g1, g2]);

        await list.moveRecord("rA", "g1", "none", "g2");

        // Record spliced into target, saved with the target column's value, no
        // revert / discard.
        expect(rA.updateChanges).toEqual({ stage_id: { id: 2, display_name: "G-g2" } });
        expect(rA.discarded).toBe(false);
        expect(steps).toEqual(["g1:remove", "g2:add", "rA:update", "g2:reseq"]);
    });
});

describe("moveRecord failed-move revert", () => {
    test("reverts the datapoint move AND discards the field change on save=false", async () => {
        const steps = [];
        const rA = makeRec("rA", steps, { updateResult: false });
        const g1 = makeGroup("g1", 1, [rA], steps);
        const g2 = makeGroup("g2", 2, [], steps);
        const list = makeList([g1, g2]);

        await list.moveRecord("rA", "g1", "none", "g2");

        expect(rA.discarded).toBe(true);
        // Move in (g1:remove, g2:add), update fails, then move back
        // (g2:remove, g1:add) AND discard — no reseq/load on the revert path.
        expect(steps).toEqual([
            "g1:remove",
            "g2:add",
            "rA:update",
            "g2:remove",
            "g1:add",
            "rA:discard",
        ]);
    });

    test("reverts and discards, then re-throws when update throws", async () => {
        const steps = [];
        const rA = makeRec("rA", steps, { updateThrows: true });
        const g1 = makeGroup("g1", 1, [rA], steps);
        const g2 = makeGroup("g2", 2, [], steps);
        const list = makeList([g1, g2]);

        let thrown = null;
        try {
            await list.moveRecord("rA", "g1", "none", "g2");
        } catch (e) {
            thrown = e;
        }

        expect(thrown).not.toBe(null);
        expect(thrown.message).toBe("save boom");
        expect(rA.discarded).toBe(true);
        expect(steps).toEqual([
            "g1:remove",
            "g2:add",
            "rA:update",
            "g2:remove",
            "g1:add",
            "rA:discard",
        ]);
    });
});
