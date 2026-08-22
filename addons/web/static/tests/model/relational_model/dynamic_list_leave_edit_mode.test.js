// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Deferred } from "@odoo/hoot-mock";
import { Mutex } from "@web/core/utils/concurrency";
import { DynamicList } from "@web/model/relational_model/dynamic_list";

describe.current.tags("headless");

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
            closeUrgentSaveNotification() {},
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

        mutex.exec(() => new Deferred());

        const result = await list.leaveEditMode();

        expect(result).toBe(true);
        expect(steps).toEqual(["r1:save"]);
    });
});
