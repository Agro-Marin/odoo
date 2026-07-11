// @ts-check

/**
 * Unit tests for DynamicList.leaveEditMode: the validate/abandon/save
 * decision tree runs inside ``model.mutex`` (``_leaveEditMode``, mirroring
 * StaticList.leaveEditMode), with a mutex-external ``_askChanges`` prelude.
 * Inside the critical section only ``_``-prefixed record internals may run —
 * the public save/discard/checkValidity re-take the mutex and would deadlock.
 *
 * Uses ``Object.create(DynamicList.prototype)`` with hand-built state,
 * mirroring dynamic_group_list_move.test.js.
 */

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { Mutex } from "@web/core/utils/concurrency";
import { DynamicList } from "@web/model/relational_model/dynamic_list";

function makeRec(
    id,
    steps,
    { isNew = false, dirty = false, valid = true, saveResult = true } = {},
) {
    return {
        id,
        isNew,
        dirty,
        config: { mode: "edit" },
        get isInEdition() {
            return this.config.mode === "edit";
        },
        _checkValidity() {
            steps.push(`${id}:checkValidity`);
            return valid;
        },
        async _save() {
            steps.push(`${id}:save`);
            return saveResult;
        },
        _discard() {
            steps.push(`${id}:discard`);
        },
    };
}

function makeList(records, steps, { mutex = new Mutex() } = {}) {
    const list = Object.create(DynamicList.prototype);
    Object.assign(list, {
        _config: {},
        _recordToDiscard: null,
        model: {
            mutex,
            urgentSave: { isActive: false },
            _closeUrgentSaveNotification: null,
            _askChanges: async () => {
                steps.push(`askChanges:${list._recordToDiscard?.id ?? "none"}`);
            },
            _patchConfig: (config, patch) => Object.assign(config, patch),
        },
        _removeRecords(ids) {
            steps.push(`remove:${ids.join(",")}`);
            for (const id of ids) {
                const index = records.findIndex((r) => r.id === id);
                if (index >= 0) {
                    records.splice(index, 1);
                }
            }
        },
    });
    // `records` is a getter-only prototype property — override per instance.
    Object.defineProperty(list, "records", { get: () => records });
    return list;
}

describe("leaveEditMode save path", () => {
    test("valid dirty record: flushed, validated, saved, switched readonly", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { dirty: true });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        // Two flushes: the historical prelude was public checkValidity()
        // followed by public save(), EACH running model._askChanges — the
        // gap between them lets reactions from the first flush (multi-edit
        // setInvalidField -> notification + discard) settle, and re-commits
        // late 'change' events before the save decision.
        expect(steps).toEqual([
            "askChanges:none",
            "askChanges:none",
            "r1:checkValidity",
            "r1:save",
        ]);
        expect(rec.config.mode).toBe("readonly");
    });

    test("a failed save keeps the row in edition and returns false", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { dirty: true, saveResult: false });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode();

        expect(result).toBe(false);
        expect(rec.config.mode).toBe("edit");
    });

    test("invalid untouched existing record just switches readonly", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { valid: false });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        expect(steps).toEqual([
            "askChanges:none",
            "askChanges:none",
            "r1:checkValidity",
        ]);
        expect(rec.config.mode).toBe("readonly");
    });

    test("new untouched record is removed without saving", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { isNew: true, dirty: false });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        expect(steps).toEqual([
            "askChanges:none",
            "askChanges:none",
            "r1:checkValidity",
            "remove:r1",
        ]);
    });

    test("no edited record: resolves true without flushing", async () => {
        const steps = [];
        const rec = makeRec("r1", steps);
        rec.config.mode = "readonly";
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        expect(steps).toEqual([]);
    });
});

describe("leaveEditMode discard path", () => {
    test("discards via _discard and removes a new record", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { isNew: true, dirty: true });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode({ discard: true });

        expect(result).toBe(true);
        // _recordToDiscard was already set during the _askChanges flush, so a
        // drained field commit can't multi-edit-dispatch the discarded edits.
        expect(steps).toEqual(["askChanges:r1", "r1:discard", "remove:r1"]);
        expect(list._recordToDiscard).toBe(null);
    });

    test("discarding an existing record switches it back to readonly", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { dirty: true });
        const list = makeList([rec], steps);

        const result = await list.leaveEditMode({ discard: true });

        expect(result).toBe(true);
        expect(steps).toEqual(["askChanges:r1", "r1:discard"]);
        expect(rec.config.mode).toBe("readonly");
        expect(list._recordToDiscard).toBe(null);
    });
});

describe("leaveEditMode concurrency", () => {
    test("the decision tree waits for the model mutex", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { dirty: true });
        const mutex = new Mutex();
        const list = makeList([rec], steps, { mutex });

        const gate = new Deferred();
        mutex.exec(() => gate);

        const prom = list.leaveEditMode();
        // Let the prelude (both flushes) run: the mutex-held critical section
        // must not have started while another job holds the mutex.
        for (let i = 0; i < 4; i++) {
            await Promise.resolve();
        }
        expect(steps).toEqual(["askChanges:none", "askChanges:none"]);

        gate.resolve();
        const result = await prom;

        expect(result).toBe(true);
        expect(steps).toEqual([
            "askChanges:none",
            "askChanges:none",
            "r1:checkValidity",
            "r1:save",
        ]);
        expect(rec.config.mode).toBe("readonly");
    });

    test("the urgent tab-close path bypasses the mutex", async () => {
        const steps = [];
        const rec = makeRec("r1", steps, { dirty: true });
        const mutex = new Mutex();
        const list = makeList([rec], steps, { mutex });
        list.model.urgentSave.isActive = true;

        // The mutex is wedged (e.g. by the very save urgent mode bypasses):
        // leaveEditMode must still complete.
        mutex.exec(() => new Deferred());

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        // No _askChanges prelude and no validity check on the urgent path.
        expect(steps).toEqual(["r1:save"]);
    });
});
