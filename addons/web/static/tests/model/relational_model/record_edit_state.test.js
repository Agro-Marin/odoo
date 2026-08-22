// @ts-check

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
    es.changes.name = "Alice";
    expect(es.changes).toEqual({ name: "Alice" });
    expect(es.isChangeSetEmpty).toBe(false);
    es.changes = { age: 30 };
    expect(es.changes).toEqual({ age: 30 });
    expect("name" in es.changes).toBe(false);
});

test("markDirty raises dirty without touching the change set (Invariant 2)", () => {
    const es = new RecordEditState();
    es.markDirty();
    expect(es.dirty).toBe(true);
    expect(es.isChangeSetEmpty).toBe(true);
});

test("clearChanges empties the bag AND lowers dirty atomically (Invariant 3)", () => {
    const es = new RecordEditState();
    es.changes.name = "Alice";
    es.markDirty();
    expect(es.dirty).toBe(true);
    expect(es.isChangeSetEmpty).toBe(false);

    es.clearChanges();

    expect(es.dirty).toBe(false);
    expect(es.isChangeSetEmpty).toBe(true);
    expect(es.changes).toEqual({});
});

test("clearChanges lowers a dirty flag even when the change set was already empty", () => {
    const es = new RecordEditState();
    es.markDirty();
    es.clearChanges();
    expect(es.dirty).toBe(false);
    expect(es.isChangeSetEmpty).toBe(true);
});

test("direct writes through the bag accumulate pending edits", () => {
    const es = new RecordEditState();
    es.changes.name = "Alice";
    es.changes.age = 30;

    expect(es.isChangeSetEmpty).toBe(false);
    expect(es.changes).toEqual({ name: "Alice", age: 30 });
    expect("name" in es.changes).toBe(true);
    expect("missing" in es.changes).toBe(false);
});

test("deleting a key through the bag removes a single field", () => {
    const es = new RecordEditState();
    es.changes.name = "Alice";
    es.changes.age = 30;
    delete es.changes.name;

    expect("name" in es.changes).toBe(false);
    expect(es.changes).toEqual({ age: 30 });
});

test("clear + write cycle does not leak prior entries", () => {
    const es = new RecordEditState();
    es.changes.a = 1;
    es.clearChanges();
    es.changes.b = 2;

    expect(es.changes).toEqual({ b: 2 });
});

test("the changes setter aliases its source rather than copying it", () => {
    const es = new RecordEditState();
    const captured = { name: "Alice" };
    es.changes = captured;

    captured.name = "Bob";

    expect(es.changes.name).toBe("Bob");
});
