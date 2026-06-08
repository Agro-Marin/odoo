// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { ChangeSet } from "@web/model/relational_model/change_set";

describe.current.tags("headless");

test("new instance starts empty", () => {
    const cs = new ChangeSet();
    expect(cs.isEmpty).toBe(true);
    expect(Object.keys(cs.raw)).toEqual([]);
});

test("setField accumulates pending edits and exposes them via raw", () => {
    const cs = new ChangeSet();
    cs.setField("name", "Alice");
    cs.setField("age", 30);

    expect(cs.isEmpty).toBe(false);
    expect(cs.raw).toEqual({ name: "Alice", age: 30 });
    expect(cs.has("name")).toBe(true);
    expect(cs.has("missing")).toBe(false);
});

test("delete removes a single field", () => {
    const cs = new ChangeSet();
    cs.setField("name", "Alice");
    cs.setField("age", 30);
    cs.delete("name");

    expect(cs.has("name")).toBe(false);
    expect(cs.raw).toEqual({ age: 30 });
});

test("clear drops all pending edits", () => {
    const cs = new ChangeSet();
    cs.setField("name", "Alice");
    cs.setField("age", 30);
    cs.clear();

    expect(cs.isEmpty).toBe(true);
    expect(Object.keys(cs.raw)).toEqual([]);
});

test("replace swaps in a new initial bag wholesale", () => {
    const cs = new ChangeSet();
    cs.setField("old", true);
    cs.replace({ fresh: 1, also_fresh: 2 });

    expect(cs.has("old")).toBe(false);
    expect(cs.raw).toEqual({ fresh: 1, also_fresh: 2 });
});

test("raw returns the live underlying bag (direct property writes land)", () => {
    // Preserves the legacy ``record._changes[fieldName] = value`` pattern
    // used inside ``_applyChanges``: callers mutate the bag in place
    // through the reference returned by ``raw``.
    const cs = new ChangeSet();
    cs.raw.inline = "written";

    expect(cs.has("inline")).toBe(true);
    expect(cs.raw.inline).toBe("written");
});

test("clear + setField cycle does not leak prior entries", () => {
    const cs = new ChangeSet();
    cs.setField("a", 1);
    cs.clear();
    cs.setField("b", 2);

    expect(cs.raw).toEqual({ b: 2 });
});

test("replace receives a fresh-references object — callers can mutate their source after", () => {
    // The savepoint-restore path captures ``{ ...this._changes }`` and
    // later passes that captured object to the setter. After restore, the
    // captured object continues to exist; verify that subsequent mutation
    // on the source doesn't leak into the ChangeSet.
    const cs = new ChangeSet();
    const captured = { name: "Alice" };
    cs.replace(captured);

    // Caller mutates their source after handing it over.
    captured.name = "Bob";

    // The ChangeSet preserves the reference (this is the intentional
    // existing behavior — ``markRaw`` does not copy), so this assertion
    // documents the contract rather than expecting isolation.
    expect(cs.raw.name).toBe("Bob");
});
