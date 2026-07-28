// @ts-check

import { afterEach, beforeEach, describe, expect, test } from "@odoo/hoot";
import { RelationalRecord } from "@web/model/relational_model/record";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

describe.current.tags("headless");

function makeFakeRecord({ dirty = false, changes = {} } = {}) {
    const editState = new RecordEditState();
    editState.changes = changes;
    return {
        _editState: editState,
        _changes: editState.changes,
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

/**
 * Minimal record mock exercising the actual `_setData` keepChanges branch
 * (commit 409786d70b9d): `this.dirty = this.dirty || !this._changeSet.isEmpty`
 * instead of deriving it solely from `_changeSet`/`_invalidFields`.
 */
function makeSetDataProbeRecord({ dirty, changes = {} } = {}) {
    return {
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
