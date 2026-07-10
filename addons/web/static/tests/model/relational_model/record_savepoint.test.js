// @ts-check

/**
 * Pure unit tests for record_savepoint.js.
 *
 * Tests addSavePoint() and restoreFromSavePoint() — the snapshot/restore
 * logic that supports discarded sub-flows (sub-form dialogs over x2many
 * children, extended-field reloads in static lists, etc.).
 *
 * Uses plain mock objects (delegation pattern, mirrors record_save.test.js).
 * OWL's markRaw() works in the Hoot browser environment without mounting
 * a component.
 *
 * Invariants under test (mirror the doc block on ``RelationalRecord.dirty``
 * in record.js):
 *
 *   - Invariant 1: ``_update()`` populates ``_changes`` and ``dirty=true``.
 *     A snapshot taken at this point must round-trip ``_changes``.
 *   - Invariant 2: ``setInvalidField()`` adds to ``_invalidFields`` with
 *     no ``_changes`` mutation.  A snapshot taken at this point must
 *     round-trip ``_invalidFields`` so dirty correctly stays true after
 *     restore.  This is the case the previous implementation got wrong
 *     ("ghost dirty" — see commit log of the introducing change).
 *   - Mixed: both populated simultaneously.
 *   - Clean: neither populated; after restore, ``dirty`` MUST be false.
 *
 * Module under test: model/relational_model/record_savepoint.js
 */

import { describe, expect, test } from "@odoo/hoot";
import { markRaw } from "@odoo/owl";
import {
    addSavePoint,
    discard,
    restoreFromSavePoint,
} from "@web/model/relational_model/record_savepoint";

// ---------------------------------------------------------------------------
// Mock factory
// ---------------------------------------------------------------------------

/**
 * Builds the minimal record mock shape required by addSavePoint() and
 * restoreFromSavePoint().
 *
 * @param {Object} [opts]
 * @param {Record<string, any>} [opts.changes]
 * @param {Record<string, any>} [opts.textValues]
 * @param {string[]} [opts.invalidFields]
 * @param {boolean} [opts.dirty]
 * @param {Record<string, { type: string }>} [opts.fields]
 * @returns {Object}
 */
function makeRecord({
    changes = {},
    textValues = {},
    invalidFields = [],
    dirty = false,
    fields = null,
} = {}) {
    // ``addSavePoint`` recurses into x2many children by reading
    // ``record.fields[fieldName].type`` for every key in ``_changes``.
    // Auto-derive a default ``char`` type for change keys not explicitly
    // typed by the test; tests that need x2many or m2o behavior pass
    // ``fields`` explicitly.
    if (fields === null) {
        fields = {};
        for (const key of Object.keys(changes)) {
            fields[key] = { type: "char" };
        }
    }
    return {
        dirty,
        _changes: markRaw({ ...changes }),
        _textValues: markRaw({ ...textValues }),
        _invalidFields: new Set(invalidFields),
        _savePoint: undefined,
        fields,
    };
}

// ---------------------------------------------------------------------------
// addSavePoint
// ---------------------------------------------------------------------------

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

        // Mutate live state after snapshot
        rec._changes.name = "B";
        rec._invalidFields.add("late_invalid");

        expect(rec._savePoint.changes).toEqual({ name: "A" });
        expect(rec._savePoint.invalidFields).toEqual([]);
    });

    test("does NOT store ``dirty`` independently — it's derived at restore", () => {
        const rec = makeRecord({ dirty: true });
        addSavePoint(rec);
        // Explicit absence: the field used to be on the snapshot and was
        // the load-bearing carrier for the Invariant-2 case.  The fix
        // moved the source of truth to _invalidFields.
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

// ---------------------------------------------------------------------------
// restoreFromSavePoint — Invariant 1 (committed changes)
// ---------------------------------------------------------------------------

describe("restoreFromSavePoint — Invariant 1 (committed _changes)", () => {
    test("round-trips _changes and derives dirty=true", () => {
        const rec = makeRecord({
            changes: { name: "Snapshot value" },
            dirty: true,
        });
        addSavePoint(rec);

        // Simulate work in a sub-flow that gets discarded
        rec._changes = markRaw({ name: "Mid-flow" });
        rec.dirty = true;

        restoreFromSavePoint(rec);

        expect(rec._changes).toEqual({ name: "Snapshot value" });
        expect(rec.dirty).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// restoreFromSavePoint — Invariant 2 (invalid input only)
// ---------------------------------------------------------------------------

describe("restoreFromSavePoint — Invariant 2 (invalid input only)", () => {
    test("round-trips _invalidFields and derives dirty=true with empty _changes", () => {
        // This is the case the previous implementation got wrong: the
        // snapshot stored ``dirty: true`` independently and after restore
        // the post-discard ``_invalidFields.clear()`` wiped the source of
        // truth, producing dirty=true with no actual issues.  Fixing the
        // snapshot to carry _invalidFields lets dirty be derived
        // correctly from ``_changes`` ∪ ``_invalidFields``.
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

        // Mutating the restored set must not corrupt the (already-consumed)
        // snapshot's array — defensive isolation matters because some
        // callers retain the snapshot reference for diagnostics.
        rec._invalidFields.add("late");
        expect(snapshotArray).toEqual(["age"]);
    });
});

// ---------------------------------------------------------------------------
// restoreFromSavePoint — mixed and clean
// ---------------------------------------------------------------------------

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
        // Pre-fix regression target: snapshotting a clean record then
        // (somehow) ending up with dirty=true at restore time would
        // produce ghost dirty.  With dirty derived from _changes ∪
        // _invalidFields, a clean snapshot ALWAYS restores to clean.
        const rec = makeRecord({ dirty: false });
        addSavePoint(rec);

        // Force live state into a falsely-dirty configuration to ensure
        // the restore path overrides, not merges.
        rec.dirty = true;

        restoreFromSavePoint(rec);

        expect(rec._changes).toEqual({});
        expect(rec._invalidFields.size).toBe(0);
        expect(rec.dirty).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// restoreFromSavePoint — _savePoint single-use semantics
// ---------------------------------------------------------------------------

describe("restoreFromSavePoint — single-use semantics", () => {
    test("consumes the savepoint after restore", () => {
        const rec = makeRecord({ changes: { name: "x" }, dirty: true });
        addSavePoint(rec);
        restoreFromSavePoint(rec);
        expect(rec._savePoint).toBe(undefined);
    });
});

// ---------------------------------------------------------------------------
// restoreFromSavePoint — _textValues
// ---------------------------------------------------------------------------

describe("restoreFromSavePoint — _textValues", () => {
    test("round-trips _textValues independently of _changes", () => {
        // _textValues tracks server-side empty-string-vs-NULL for char/
        // text/html fields.  It can be populated even when _changes is
        // empty (e.g. user typed then backspaced — _changes drops the
        // entry but _textValues keeps the empty-string history).
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

// ===========================================================================
// discard — added in Phase 5 of the model-layer decomposition
// (workspaces/workspace-LMMG/brainstorms/2026-05-23-web-model-layer-decomposition.md).
//
// Invariants under test:
//   - I3 (atomic _changes + dirty clear) — the no-savepoint branch must
//     route through record._clearChanges() so _changes and dirty reset on
//     the same step. Test asserts both are reset post-discard.
//   - I8 (savepoint restoration) — the savepoint branch must NOT wipe
//     _invalidFields (the snapshot already carries them); only the
//     no-savepoint branch performs the .clear().
//   - Validity re-check skipped when isNew (new draft); runs otherwise.
//   - x2many child._discard() is invoked BEFORE the parent's main logic
//     so the rebuild reads consistent child state.
//   - Closes the invalid-fields notification and resets the closer.
//   - Calls _restoreActiveFields at the end of the discard sequence.
// ===========================================================================

/**
 * Build a record mock for discard tests. Provides the wider surface
 * that discard reads/mutates beyond what addSavePoint needs.
 *
 * @param {Object} [opts]
 * @param {boolean} [opts.hasSavePoint=false]
 * @param {boolean} [opts.isNew=false]
 * @param {Object} [opts.values={}]
 * @param {Object} [opts.changes={}]
 * @param {Object} [opts.initialTextValues={}]
 * @param {string[]} [opts.invalid=[]]
 * @param {Object} [opts.savePoint=null] - explicit snapshot to install
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
    // Auto-populate fields with a safe "char" default for every key in
    // ``changes`` and ``values``. The real RelationalRecord guarantees
    // ``record.fields[fieldName]`` is defined for every active field; the
    // helper reads ``record.fields[fieldName].type`` in the x2many child
    // cascade and would throw on ``undefined.type``. Individual tests
    // override by passing an explicit ``fields`` (e.g. the x2many cascade
    // tests pass ``{ line_ids: { type: "one2many" } }``).
    /** @type {any} */
    const autoFields = fields ?? {};
    if (!fields) {
        for (const key of Object.keys({ ...values, ...changes })) {
            autoFields[key] = { type: "char" };
        }
    }
    /** @type {any} */
    const rec = {
        fields: autoFields,
        isNew,
        dirty: Object.keys(changes).length > 0 || invalid.length > 0,
        data: { ...values, ...changes },
        _values: { ...values },
        _changes: markRaw({ ...changes }),
        _textValues: markRaw({}),
        _initialTextValues: { ...initialTextValues },
        _invalidFields: new Set(invalid),
        _closeInvalidFieldsNotification: () => {},
        _setEvalContext: () => {},
        _checkValidity: () => true,
        _restoreActiveFields: () => {},
        _clearChanges() {
            // Invariant I3 — atomic pair
            this._changes = markRaw({});
            this.dirty = false;
        },
        _savePoint: hasSavePoint
            ? (savePoint ??
              markRaw({
                  changes: { ...changes },
                  textValues: {},
                  invalidFields: [...invalid],
              }))
            : undefined,
    };
    return rec;
}

// ---------------------------------------------------------------------------
// discard — no savepoint path (I3 + invalidFields wipe + textValues reset)
// ---------------------------------------------------------------------------

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
        // _changes was cleared; rebuild reads only _values.
        expect(rec.data).toEqual({ name: "server", age: 30 });
    });
});

// ---------------------------------------------------------------------------
// discard — savepoint path (I8 — restored state survives)
// ---------------------------------------------------------------------------

describe("discard — savepoint path (restore snapshot)", () => {
    test("calls restoreFromSavePoint: _changes/_textValues/_invalidFields back to snapshot", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            values: { name: "server" },
            savePoint: markRaw({
                changes: { name: "snapshot-edit" },
                textValues: { description: "snapshot-text" },
                invalidFields: ["email"],
            }),
        });
        // Pre-discard state: different from the snapshot.
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
            savePoint: markRaw({
                changes: { name: "snapshot-edit" },
                textValues: {},
                invalidFields: [],
            }),
        });
        discard(rec);
        // Snapshot had changes → dirty=true.
        expect(rec.dirty).toBe(true);
    });

    test("savepoint branch does NOT wipe _invalidFields (preserved from snapshot)", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            savePoint: markRaw({
                changes: {},
                textValues: {},
                invalidFields: ["email"],
            }),
        });
        // Pre-discard, some non-snapshot invalid field also present.
        rec._invalidFields = new Set(["email", "noise"]);
        discard(rec);
        // After restore: ONLY the snapshot's invalidFields survive; the
        // no-savepoint branch's _invalidFields.clear() does NOT run here.
        expect([...rec._invalidFields]).toEqual(["email"]);
    });

    test("rebuilds data from _values + restored _changes", () => {
        const rec = makeDiscardRecord({
            hasSavePoint: true,
            values: { name: "server", age: 30 },
            savePoint: markRaw({
                changes: { name: "from-snapshot" },
                textValues: {},
                invalidFields: [],
            }),
        });
        discard(rec);
        expect(rec.data).toEqual({ name: "from-snapshot", age: 30 });
    });
});

// ---------------------------------------------------------------------------
// discard — common post-branch behavior
// ---------------------------------------------------------------------------

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
        rec._closeInvalidFieldsNotification = originalCloser;
        discard(rec);
        expect(closeCalled).toBe(true);
        // Closer reset to a NEW no-op function (not the original closer).
        expect(rec._closeInvalidFieldsNotification).not.toBe(originalCloser);
        // Calling the reset closer is safe — no-op, doesn't throw.
        rec._closeInvalidFieldsNotification();
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

// ---------------------------------------------------------------------------
// discard — x2many child cascade
// ---------------------------------------------------------------------------

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
        // Wrap _clearChanges so we can observe relative order.
        const origClear = rec._clearChanges.bind(rec);
        rec._clearChanges = () => {
            order.push("_clearChanges");
            origClear();
        };
        discard(rec);
        // child._discard runs first; the parent's _clearChanges runs after.
        expect(order).toEqual(["child._discard", "_clearChanges"]);
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
