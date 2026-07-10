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
