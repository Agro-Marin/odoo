// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Mutex } from "@web/core/utils/concurrency";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";
import { UrgentSaveCoordinator } from "@web/model/relational_model/urgent_save_coordinator";

describe.current.tags("headless");

/**
 * @param {{ urgent?: boolean, dispatch: () => any }} params
 */
function makeRecord({ urgent = false, dispatch }) {
    const urgentSave = new UrgentSaveCoordinator();
    /** @type {any[][]} */
    const dispatched = [];
    const record = Object.create(RelationalRecord.prototype);
    Object.assign(record, {
        model: {
            urgentSave,
            multiEdit: true,
            mutex: new Mutex(),
            multiEditDispatch: (/** @type {any[]} */ ...args) => {
                dispatched.push(args);
                return dispatch();
            },
            hasOnRecordChangedHook: false,
            notifyLifecycle: async () => {},
        },
        selected: true,
        canSaveOnUpdate: true,
        data: { x: "old" },
        _config: {
            fields: { x: { name: "x", type: "char" } },
            activeFields: { x: {} },
        },
        _editState: new RecordEditState(),
        _onUpdate: () => {},
    });
    record._markDirty = () => {};
    record._preprocessChanges = async () => {};
    record._snapshotTouchedLists = () => /** @type {any[]} */ ([]);
    return { record, urgentSave, urgent, dispatched };
}

/**
 * @param {ReturnType<typeof makeRecord>} harness
 */
async function callUpdate(harness) {
    const run = () =>
        RelationalRecord.prototype.update.call(harness.record, { x: "v" });
    if (harness.urgent) {
        return harness.urgentSave.run(run);
    }
    return run();
}

describe("update() opens the multi-edit envelope", () => {
    test("a refused multi-save reads as false, not as an object", async () => {
        const result = await callUpdate(makeRecord({ dispatch: () => false }));
        expect(result).toBe(false);
    });

    test("...and the same holds during an urgent save", async () => {
        const result = await callUpdate(
            makeRecord({ urgent: true, dispatch: () => false }),
        );
        expect(result).toBe(false);
    });

    test("an accepted multi-save reads as true through both exits", async () => {
        expect(await callUpdate(makeRecord({ dispatch: () => true }))).toBe(true);
        expect(
            await callUpdate(makeRecord({ urgent: true, dispatch: () => true })),
        ).toBe(true);
    });
});

describe("_update rolls the x2many snapshots back", () => {
    test("when the multi-edit dispatch rejects", async () => {
        const harness = makeRecord({
            dispatch: () => Promise.reject(new Error("boom")),
        });
        /** @type {any[]} */
        const restored = [];
        harness.record._snapshotTouchedLists = () => [
            {
                list: {
                    _restore: (/** @type {any} */ snapshot) => restored.push(snapshot),
                },
                snapshot: "snap",
            },
        ];
        await expect(callUpdate(harness)).rejects.toThrow("boom");
        expect(restored).toEqual(["snap"]);
    });
});
