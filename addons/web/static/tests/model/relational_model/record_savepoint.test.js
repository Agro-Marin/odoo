// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import { makeRecordDouble } from "@web/../tests/model/relational_model/record_doubles";
import {
    addSavePoint,
    createSavePoint,
    discard,
    restoreFromSavePoint,
} from "@web/model/relational_model/record_savepoint";

/**
 * @param {Object} [opts]
 * @param {Record<string, any>} [opts.changes]
 * @param {Record<string, any>} [opts.textValues]
 * @param {string[]} [opts.invalidFields]
 * @param {string[]} [opts.unsetRequiredFields]
 * @param {boolean} [opts.dirty]
 * @param {Record<string, { type: string }>} [opts.fields]
 * @returns {Object}
 */
function makeRecord({
    changes = {},
    textValues = {},
    invalidFields = [],
    unsetRequiredFields = invalidFields,
    dirty = false,
    fields = null,
} = {}) {
    return makeRecordDouble({
        changes,
        textValues,
        invalidFields,
        unsetRequiredFields,
        dirty,
        fields,
        data: { ...changes },
    });
}

describe("addSavePoint", () => {
    test("snapshots _changes, _textValues, _invalidFields", () => {
        const rec = makeRecord({
            changes: { name: "Edited", age: 30 },
            textValues: { name: "Edited" },
            invalidFields: ["bad_field"],
        });

        addSavePoint(rec);

        expect(rec._savePoint).not.toBe(undefined);
        expect(rec._savePoint.changes).toEqual({ name: "Edited", age: 30 });
        expect(rec._savePoint.textValues).toEqual({ name: "Edited" });
        expect(rec._savePoint.invalidFields).toEqual(["bad_field"]);
    });

    test("snapshot is decoupled from live state — mutations don't leak", () => {
        const rec = makeRecord({ changes: { name: "A" } });
        addSavePoint(rec);

        rec._changes.name = "B";
        rec._invalidFields.add("late_invalid");

        expect(rec._savePoint.changes).toEqual({ name: "A" });
        expect(rec._savePoint.invalidFields).toEqual([]);
    });

    test("does NOT store ``dirty`` independently — it's derived at restore", () => {
        const rec = makeRecord({ dirty: true });
        addSavePoint(rec);
        expect("dirty" in rec._savePoint).toBe(false);
    });

    test("recurses into x2many children when _changes contains them", () => {
        let childSnapshotCalls = 0;
        const childList = {
            _addSavePoint: () => {
                childSnapshotCalls++;
            },
        };
        const rec = makeRecord({
            changes: { lines: childList, name: "Top" },
            fields: {
                lines: { type: "one2many" },
                name: { type: "char" },
            },
        });

        addSavePoint(rec);

        expect(childSnapshotCalls).toBe(1);
    });

    test("does not recurse into non-x2many fields", () => {
        let childSnapshotCalls = 0;
        const m2oValue = {
            id: 5,
            display_name: "Foo",
            _addSavePoint: () => {
                childSnapshotCalls++;
            },
        };
        const rec = makeRecord({
            changes: { partner_id: m2oValue },
            fields: { partner_id: { type: "many2one" } },
        });

        addSavePoint(rec);

        expect(childSnapshotCalls).toBe(0);
    });
});

describe("restoreFromSavePoint — Invariant 1 (committed _changes)", () => {
    test("round-trips _changes and derives dirty=true", () => {
        const rec = makeRecord({
            changes: { name: "Snapshot value" },
            dirty: true,
        });
        addSavePoint(rec);

        rec._changes = markRaw({ name: "Mid-flow" });
        rec.dirty = true;

        restoreFromSavePoint(rec);

        expect(rec._changes).toEqual({ name: "Snapshot value" });
        expect(rec.dirty).toBe(true);
    });
});

describe("restoreFromSavePoint — Invariant 2 (invalid input only)", () => {
    test("round-trips _invalidFields and derives dirty=true with empty _changes", () => {
        const rec = makeRecord({
            invalidFields: ["age"],
            dirty: true,
        });
        addSavePoint(rec);

        rec._invalidFields.clear();
        rec.dirty = false;

        restoreFromSavePoint(rec);

        expect(rec._invalidFields.has("age")).toBe(true);
        expect(rec._invalidFields.size).toBe(1);
        expect(rec.dirty).toBe(true);
    });

    test("the restored _invalidFields is a NEW Set — not a reference into the snapshot", () => {
        const rec = makeRecord({ invalidFields: ["age"], dirty: true });
        addSavePoint(rec);
        const snapshotArray = rec._savePoint.invalidFields;

        rec._invalidFields = new Set();
        restoreFromSavePoint(rec);

        rec._invalidFields.add("late");
        expect(snapshotArray).toEqual(["age"]);
    });
});

describe("restoreFromSavePoint — mixed state", () => {
    test("both _changes and _invalidFields populated → dirty=true", () => {
        const rec = makeRecord({
            changes: { name: "Edited" },
            invalidFields: ["age"],
            dirty: true,
        });
        addSavePoint(rec);

        rec._changes = markRaw({});
        rec._invalidFields.clear();
        rec.dirty = false;

        restoreFromSavePoint(rec);

        expect(rec._changes).toEqual({ name: "Edited" });
        expect(rec._invalidFields.has("age")).toBe(true);
        expect(rec.dirty).toBe(true);
    });
});

describe("restoreFromSavePoint — clean state", () => {
    test("no _changes and no _invalidFields → dirty=false (no ghost dirty)", () => {
        const rec = makeRecord({ dirty: false });
        addSavePoint(rec);

        rec.dirty = true;

        restoreFromSavePoint(rec);

        expect(rec._changes).toEqual({});
        expect(rec._invalidFields.size).toBe(0);
        expect(rec.dirty).toBe(false);
    });
});

describe("restoreFromSavePoint — single-use semantics", () => {
    test("consumes the savepoint after restore", () => {
        const rec = makeRecord({ changes: { name: "x" }, dirty: true });
        addSavePoint(rec);
        restoreFromSavePoint(rec);
        expect(rec._savePoint).toBe(undefined);
    });
});

describe("restoreFromSavePoint — _textValues", () => {
    test("round-trips _textValues independently of _changes", () => {
        const rec = makeRecord({
            textValues: { description: "" },
            changes: {},
            dirty: false,
        });
        addSavePoint(rec);

        rec._textValues = markRaw({ description: "mutated" });
        restoreFromSavePoint(rec);

        expect(rec._textValues).toEqual({ description: "" });
    });
});

/**
 * @param {Object} [opts]
 * @param {boolean} [opts.hasSavePoint=false]
 * @param {boolean} [opts.isNew=false]
 * @param {Object} [opts.values={}]
 * @param {Object} [opts.changes={}]
 * @param {Object} [opts.initialTextValues={}]
 * @param {string[]} [opts.invalid=[]]
 * @param {Object} [opts.savePoint=null]
 * @returns {Object}
 */
function makeDiscardRecord({
    hasSavePoint = false,
    isNew = false,
    values = {},
    changes = {},
    initialTextValues = {},
    invalid = [],
    savePoint = null,
    fields = null,
} = {}) {
    const rec = makeRecordDouble({
        isNew,
        values,
        changes,
        initialTextValues,
        invalidFields: invalid,
        fields,
        dirty: Object.keys(changes).length > 0 || invalid.length > 0,
    });
    rec._savePoint = hasSavePoint
        ? (savePoint ??
          createSavePoint({
              changes,
              invalidFields: invalid,
              unsetRequiredFields: invalid,
          }))
        : undefined;
    return rec;
}

describe("discard — no savepoint (clear to server truth)", () => {
    test("calls _clearChanges so _changes={} and dirty=false (Invariant I3)", () => {
        const rec = makeDiscardRecord({
            values: { name: "server" },
            changes: { name: "user-edit" },
        });
        expect(rec.dirty).toBe(true);
        discard(rec);
        expect(rec._changes).toEqual({});
        expect(rec.dirty).toBe(false);
    });

    test("resets _textValues from _initialTextValues snapshot", () => {
        const rec = makeDiscardRecord({
            initialTextValues: { description: "initial server text" },
        });
        rec._textValues = markRaw({ description: "mutated by user" });
        discard(rec);
        expect(rec._textValues).toEqual({ description: "initial server text" });
    });

    test("wipes _invalidFields (stale by construction once data is back to _values)", () => {
        const rec = makeDiscardRecord({
            values: { name: "x" },
            invalid: ["name", "email"],
        });
        discard(rec);
        expect([...rec._invalidFields]).toEqual([]);
    });

    test("rebuilds data from _values + _changes (post-clear)", () => {
        const rec = makeDiscardRecord({
            values: { name: "server", age: 30 },
            changes: { name: "edit", age: 99 },
        });
        discard(rec);
        expect(rec.data).toEqual({ name: "server", age: 30 });
    });
});

describe("discard — savepoint path (restore snapshot)", () => {
    test("calls restoreFromSavePoint: _changes/_textValues/_invalidFields back to snapshot", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            values: { name: "server" },
            savePoint: createSavePoint({
                changes: { name: "snapshot-edit" },
                textValues: { description: "snapshot-text" },
                invalidFields: ["email"],
                unsetRequiredFields: ["email"],
            }),
        });
        rec._changes = markRaw({ name: "post-snapshot edit" });
        rec._textValues = markRaw({ description: "post-snapshot text" });
        rec._invalidFields = new Set(["other"]);
        discard(rec);
        expect(rec._changes).toEqual({ name: "snapshot-edit" });
        expect(rec._textValues).toEqual({ description: "snapshot-text" });
        expect([...rec._invalidFields]).toEqual(["email"]);
    });

    test("derives dirty from restored _changes + _invalidFields (snapshot truth)", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            values: { name: "server" },
            savePoint: createSavePoint({
                changes: { name: "snapshot-edit" },
            }),
        });
        discard(rec);
        expect(rec.dirty).toBe(true);
    });

    test("savepoint branch does NOT wipe _invalidFields (preserved from snapshot)", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            savePoint: createSavePoint({
                invalidFields: ["email"],
                unsetRequiredFields: ["email"],
            }),
        });
        rec._invalidFields = new Set(["email", "noise"]);
        discard(rec);
        expect([...rec._invalidFields]).toEqual(["email"]);
    });

    test("rebuilds data from _values + restored _changes", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            values: { name: "server", age: 30 },
            savePoint: createSavePoint({
                changes: { name: "from-snapshot" },
            }),
        });
        discard(rec);
        expect(rec.data).toEqual({ name: "from-snapshot", age: 30 });
    });
});

describe("discard — common post-branch behavior", () => {
    test("re-runs _checkValidity when !isNew", () => {
        let called = false;
        const rec = makeDiscardRecord({ isNew: false });
        rec._checkValidity = () => {
            called = true;
            return true;
        };
        discard(rec);
        expect(called).toBe(true);
    });

    test("skips _checkValidity when isNew (new draft)", () => {
        let called = false;
        const rec = makeDiscardRecord({ isNew: true });
        rec._checkValidity = () => {
            called = true;
            return true;
        };
        discard(rec);
        expect(called).toBe(false);
    });

    test("closes the invalid-fields notification and resets the closer to a no-op", () => {
        let closeCalled = false;
        const rec = makeDiscardRecord();
        const originalCloser = () => {
            closeCalled = true;
        };
        rec.setInvalidFieldsNotification(originalCloser);
        discard(rec);
        expect(closeCalled).toBe(true);
        closeCalled = false;
        rec.closeInvalidFieldsNotification();
        expect(closeCalled).toBe(false);
    });

    test("calls _restoreActiveFields at the end of the discard sequence", () => {
        let called = false;
        const rec = makeDiscardRecord();
        rec._restoreActiveFields = () => {
            called = true;
        };
        discard(rec);
        expect(called).toBe(true);
    });

    test("refreshes the eval context after the rebuild", () => {
        let called = false;
        const rec = makeDiscardRecord();
        rec._setEvalContext = () => {
            called = true;
        };
        discard(rec);
        expect(called).toBe(true);
    });
});

describe("discard — x2many child._discard() cascade", () => {
    test("calls _discard on each x2many StaticList in _changes BEFORE the parent's main logic", () => {
        const order = [];
        const childList = {
            _discard() {
                order.push("child._discard");
            },
        };
        const rec = makeDiscardRecord({
            changes: { line_ids: childList },
        });
        rec.fields = { line_ids: { type: "one2many" } };
        const origDiscardChanges = rec._discardChanges.bind(rec);
        rec._discardChanges = () => {
            order.push("_discardChanges");
            origDiscardChanges();
        };
        discard(rec);
        expect(order).toEqual(["child._discard", "_discardChanges"]);
        expect({ .../** @type {any} */ (rec)._changes }).toEqual({});
    });

    test("does NOT call _discard on scalar fields in _changes", () => {
        let scalarDiscardCalled = false;
        const scalarField = {
            _discard() {
                scalarDiscardCalled = true;
            },
        };
        const rec = makeDiscardRecord({
            changes: { name: scalarField },
        });
        rec.fields = { name: { type: "char" } };
        discard(rec);
        expect(scalarDiscardCalled).toBe(false);
    });
});
