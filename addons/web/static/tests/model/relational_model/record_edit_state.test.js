// @ts-check

/**
 * Unit tests for RecordEditState — the owner object that holds a record's
 * editable-state layer (pending change set, dirty flag, validity sets,
 * text-value tracking, savepoint). These pin the structural guarantees the
 * owner adds: the atomic (dirty, changes) invariant and the change-bag
 * accessors. Behavioural coverage of how the record and its sibling helpers
 * drive this owner lives in record_save/record_savepoint/record_validator/
 * record_dirty_rollback tests.
 */

import { describe, expect, test } from "@odoo/hoot";
import { RecordEditState } from "@web/model/relational_model/record_edit_state";

describe.current.tags("headless");

test("fresh owner is clean: not dirty, empty change set, no invalid fields", () => {
    const es = new RecordEditState();
    expect(es.dirty).toBe(false);
    expect(es.isChangeSetEmpty).toBe(true);
    expect(es.changes).toEqual({});
    expect(es.invalidFields.size).toBe(0);
    expect(es.unsetRequiredFields.size).toBe(0);
});

test("changes getter exposes the bag by reference; setter replaces it", () => {
    const es = new RecordEditState();
    // Single-field write lands on the same bag the getter returns.
    es.changes.name = "Alice";
    expect(es.changes).toEqual({ name: "Alice" });
    expect(es.isChangeSetEmpty).toBe(false);
    // Wholesale replace goes through ChangeSet.replace (markRaw preserved).
    es.changes = { age: 30 };
    expect(es.changes).toEqual({ age: 30 });
    expect("name" in es.changes).toBe(false);
});

test("markDirty raises dirty without touching the change set (Invariant 2)", () => {
    const es = new RecordEditState();
    es.markDirty();
    expect(es.dirty).toBe(true);
    // Invalid-input case: dirty coexists with an empty change set.
    expect(es.isChangeSetEmpty).toBe(true);
});

test("clearChanges empties the bag AND lowers dirty atomically (Invariant 3)", () => {
    const es = new RecordEditState();
    es.changes.name = "Alice";
    es.markDirty();
    expect(es.dirty).toBe(true);
    expect(es.isChangeSetEmpty).toBe(false);

    es.clearChanges();

    // The illegal (dirty=false, non-empty changes) state is never observable
    // between these two: clearChanges is the single atomic reset.
    expect(es.dirty).toBe(false);
    expect(es.isChangeSetEmpty).toBe(true);
    expect(es.changes).toEqual({});
});

test("clearChanges lowers a dirty flag even when the change set was already empty", () => {
    // The Invariant-1 window (dirty=true, changes empty) collapses to clean.
    const es = new RecordEditState();
    es.markDirty();
    es.clearChanges();
    expect(es.dirty).toBe(false);
    expect(es.isChangeSetEmpty).toBe(true);
});
