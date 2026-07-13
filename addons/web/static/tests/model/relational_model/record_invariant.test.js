// @ts-check

import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { ChangeSet } from "@web/model/relational_model/change_set";
import { RelationalRecord } from "@web/model/relational_model/record";

describe.current.tags("headless");

// _assertChangeSetInvariant only reads this._changeSet, this.dirty,
// this.resModel, this.resId — minimal mock avoids the full model setup
// the other record tests require.
function makeFakeRecord({ dirty = false, changes = {} } = {}) {
    const cs = new ChangeSet();
    cs.replace(changes);
    return {
        _changeSet: cs,
        _changes: cs.raw,
        dirty,
        resModel: "test.model",
        resId: 42,
        _assertChangeSetInvariant: RelationalRecord.prototype._assertChangeSetInvariant,
    };
}

let originalDebug;
let warnings;
let originalWarn;

beforeEach(() => {
    originalDebug = odoo.debug;
    warnings = [];
    originalWarn = console.warn;
    console.warn = (...args) => warnings.push(args.join(" "));
});

afterEach(() => {
    odoo.debug = originalDebug;
    console.warn = originalWarn;
});

test("clean state (dirty=false, changes empty) passes silently", () => {
    odoo.debug = "1";
    const rec = makeFakeRecord();
    rec._assertChangeSetInvariant();
    expect(warnings).toEqual([]);
});

test("modified state (dirty=true, changes non-empty) passes silently", () => {
    odoo.debug = "1";
    const rec = makeFakeRecord({ dirty: true, changes: { name: "alice" } });
    rec._assertChangeSetInvariant();
    expect(warnings).toEqual([]);
});

test("invalid-input state (dirty=true, changes empty) passes silently", () => {
    odoo.debug = "1";
    const rec = makeFakeRecord({ dirty: true, changes: {} });
    rec._assertChangeSetInvariant();
    expect(warnings).toEqual([]);
});

test("DESYNC state (dirty=false, changes non-empty) warns in debug mode", () => {
    odoo.debug = "1";
    const rec = makeFakeRecord({ dirty: false, changes: { name: "alice" } });
    rec._assertChangeSetInvariant();
    expect(warnings.length).toBe(1);
    expect(warnings[0]).toInclude("ChangeSet invariant violated");
    expect(warnings[0]).toInclude("test.model/42");
    expect(warnings[0]).toInclude("name");
});

test("DESYNC state is silent in production (odoo.debug=false)", () => {
    odoo.debug = false;
    const rec = makeFakeRecord({ dirty: false, changes: { name: "alice" } });
    rec._assertChangeSetInvariant();
    expect(warnings).toEqual([]);
});

test("keepChanges reload derives dirty, so the invariant holds on that path too", () => {
    // The former ``allowKeepChanges`` escape hatch is gone: _setData's
    // keepChanges branch now sets ``dirty = !changeSet.isEmpty`` instead
    // of blindly resetting the flag, so the desync state can no longer
    // be produced by the reload path.
    odoo.debug = "1";
    const rec = makeFakeRecord({ dirty: true, changes: { name: "alice" } });
    rec._assertChangeSetInvariant();
    expect(warnings).toEqual([]);
});

test("warning message includes /new for unsaved records", () => {
    odoo.debug = "1";
    const rec = makeFakeRecord({ dirty: false, changes: { name: "alice" } });
    rec.resId = false;
    rec._assertChangeSetInvariant();
    expect(warnings[0]).toInclude("test.model/new");
});

// ---------------------------------------------------------------------------
// _setData(keepChanges=true) — the dirty flag is never lowered on reload
// ---------------------------------------------------------------------------

/**
 * Minimal record mock exercising the actual `_setData` keepChanges branch
 * (commit 409786d70b9d): `this.dirty = this.dirty || !this._changeSet.isEmpty`
 * instead of deriving it solely from `_changeSet`/`_invalidFields`.
 */
function makeSetDataProbeRecord({ dirty, changes = {} } = {}) {
    return {
        // Reuses makeFakeRecord's ChangeSet/dirty/resId/_assertChangeSetInvariant
        // setup; only the extra state _setData's keepChanges branch reads is
        // added on top (_invalidFields/_values/_checkValidity are untouched on
        // that branch and deliberately omitted).
        ...makeFakeRecord({ dirty, changes }),
        _textValues: {},
        isNew: false,
        isInEdition: false,
        _parentRecord: null,
        _parseServerValues: (data) => data,
        _getTextValues: () => ({}),
        _setEvalContext() {},
        _setData: RelationalRecord.prototype._setData,
    };
}

describe("_setData(keepChanges) dirty derivation", () => {
    test("Invariant-1 window: dirty=true with an empty changeSet survives a reload", () => {
        // Between _markDirty() and _applyChanges() in an in-flight _update(),
        // the record is dirty but _changes is still empty. Pre-fix, deriving
        // dirty purely from `!changeSet.isEmpty` here would silently clear it
        // and the next isDirty() gate (pager, action buttons) would discard
        // the pending edit.
        const rec = makeSetDataProbeRecord({ dirty: true, changes: {} });
        rec._setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(true);
    });

    test("clean record with pending changes becomes dirty", () => {
        const rec = makeSetDataProbeRecord({ dirty: false, changes: { name: "x" } });
        rec._setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(true);
    });

    test("clean record with no pending changes stays clean", () => {
        const rec = makeSetDataProbeRecord({ dirty: false, changes: {} });
        rec._setData({ id: 1 }, { keepChanges: true });
        expect(rec.dirty).toBe(false);
    });
});
