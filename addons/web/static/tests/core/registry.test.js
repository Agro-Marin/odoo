// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component } from "@odoo/owl";
import { patchWithCleanup, serverState } from "@web/../tests/web_test_helpers";
import { Registry } from "@web/core/registry";

describe.current.tags("headless");

test("key set and get", () => {
    const registry = new Registry();
    const foo = {};

    registry.add("foo", foo);

    expect(registry.get("foo")).toBe(foo);
});

test("can set and get falsy values", () => {
    const registry = new Registry();
    registry.add("foo1", false);
    registry.add("foo2", 0);
    registry.add("foo3", "");
    registry.add("foo4", undefined);
    registry.add("foo5", null);

    expect(registry.get("foo1")).toBe(false);
    expect(registry.get("foo2")).toBe(0);
    expect(registry.get("foo3")).toBe("");
    expect(registry.get("foo4")).toBe(undefined);
    expect(registry.get("foo5")).toBe(null);
});

test("can set and get falsy values with default value", () => {
    const registry = new Registry();
    registry.add("foo1", false);
    registry.add("foo2", 0);
    registry.add("foo3", "");
    registry.add("foo4", undefined);
    registry.add("foo5", null);

    expect(registry.get("foo1", 1)).toBe(false);
    expect(registry.get("foo2", 1)).toBe(0);
    expect(registry.get("foo3", 1)).toBe("");
    expect(registry.get("foo4", 1)).toBe(undefined);
    expect(registry.get("foo5", 1)).toBe(null);
});

test("can get a default value when missing key", () => {
    const registry = new Registry();

    expect(registry.get("missing", "default")).toBe("default");
    expect(registry.get("missing", null)).toBe(null);
    expect(registry.get("missing", false)).toBe(false);
});

test("throws if key is missing", () => {
    const registry = new Registry();
    expect(() => registry.get("missing")).toThrow();
});

test("contains method", () => {
    const registry = new Registry();

    registry.add("foo", 1);

    expect(registry.contains("foo")).toBe(true);
    expect(registry.contains("bar")).toBe(false);
});

test("can set and get a value, with an order arg", () => {
    const registry = new Registry();
    const foo = {};

    registry.add("foo", foo, { sequence: 24 });

    expect(registry.get("foo")).toBe(foo);
});

test("can get ordered list of elements", () => {
    const registry = new Registry();

    registry
        .add("foo1", "foo1", { sequence: 1 })
        .add("foo2", "foo2", { sequence: 2 })
        .add("foo5", "foo5", { sequence: 5 })
        .add("foo3", "foo3", { sequence: 3 });

    expect(registry.getAll()).toEqual(["foo1", "foo2", "foo3", "foo5"]);
});

test("can get ordered list of entries", () => {
    const registry = new Registry();

    registry
        .add("foo1", "foo1", { sequence: 1 })
        .add("foo2", "foo2", { sequence: 2 })
        .add("foo5", "foo5", { sequence: 5 })
        .add("foo3", "foo3", { sequence: 3 });

    expect(registry.getEntries()).toEqual([
        ["foo1", "foo1"],
        ["foo2", "foo2"],
        ["foo3", "foo3"],
        ["foo5", "foo5"],
    ]);
});

test("getAll and getEntries return frozen cached arrays", () => {
    const registry = new Registry();

    registry.add("foo1", "foo1");

    const all = registry.getAll();
    const entries = registry.getEntries();

    expect(all).toEqual(["foo1"]);
    expect(entries).toEqual([["foo1", "foo1"]]);

    // Arrays are frozen — mutation throws in strict mode
    expect(() => all.push("foo2")).toThrow();
    expect(() => entries.push(["foo2", "foo2"])).toThrow();

    // Cached array is unchanged
    expect(registry.getAll()).toEqual(["foo1"]);
    expect(registry.getEntries()).toEqual([["foo1", "foo1"]]);
});

test("getAll and getEntries return the same cached reference", () => {
    const registry = new Registry();
    registry.add("a", 1);

    // Same reference on repeated calls (no unnecessary copy)
    expect(registry.getAll()).toBe(registry.getAll());
    expect(registry.getEntries()).toBe(registry.getEntries());

    // Adding invalidates cache — new reference
    const prev = registry.getAll();
    registry.add("b", 2);
    expect(registry.getAll()).not.toBe(prev);
});

test("getAll/getEntries: callers can spread for mutable copy", () => {
    const registry = new Registry();
    registry.add("b", "b", { sequence: 2 });
    registry.add("a", "a", { sequence: 1 });

    // Spread creates a mutable copy
    const sorted = [...registry.getAll()];
    expect(() => sorted.reverse()).not.toThrow();
    expect(sorted).toEqual(["b", "a"]);

    // Original frozen cache unchanged
    expect(registry.getAll()).toEqual(["a", "b"]);
});

test("can override element with sequence", () => {
    const registry = new Registry();

    registry
        .add("foo1", "foo1", { sequence: 1 })
        .add("foo2", "foo2", { sequence: 2 })
        .add("foo1", "foo3", { force: true });

    expect(registry.getEntries()).toEqual([
        ["foo1", "foo3"],
        ["foo2", "foo2"],
    ]);
});

test("can override element with sequence 2 ", () => {
    const registry = new Registry();

    registry
        .add("foo1", "foo1", { sequence: 1 })
        .add("foo2", "foo2", { sequence: 2 })
        .add("foo1", "foo3", { force: true, sequence: 3 });

    expect(registry.getEntries()).toEqual([
        ["foo2", "foo2"],
        ["foo1", "foo3"],
    ]);
});

test("force-replacing preserves sequence 0", () => {
    const registry = new Registry();

    registry
        .add("first", "a", { sequence: 0 })
        .add("second", "b", { sequence: 1 });

    // Force-replace without specifying sequence — should keep sequence 0
    registry.add("first", "a2", { force: true });

    // "first" should still sort before "second" (sequence 0 < 1)
    expect(registry.getEntries()).toEqual([
        ["first", "a2"],
        ["second", "b"],
    ]);
});

test("contains is not fooled by Object.prototype keys", () => {
    const registry = new Registry();

    // These are inherited keys on a regular {} object.
    // With Object.create(null), they correctly return false.
    expect(registry.contains("constructor")).toBe(false);
    expect(registry.contains("toString")).toBe(false);
    expect(registry.contains("hasOwnProperty")).toBe(false);
    expect(registry.contains("__proto__")).toBe(false);

    // But explicitly added keys work
    registry.add("constructor", "my-value");
    expect(registry.contains("constructor")).toBe(true);
    expect(registry.get("constructor")).toBe("my-value");
});

test("can recursively open sub registry", () => {
    const registry = new Registry();

    registry.category("sub").add("a", "b");
    expect(registry.category("sub").get("a")).toBe("b");
});

test("can validate the values from a schema", () => {
    serverState.debug = "1";
    const schema = { name: String, age: { type: Number, optional: true } };
    const friendsRegistry = new Registry();
    friendsRegistry.addValidation(schema);
    expect(() => friendsRegistry.add("jean", { name: "Jean" })).not.toThrow();
    expect(friendsRegistry.get("jean")).toEqual({ name: "Jean" });
    expect(() => friendsRegistry.add("luc", { name: "Luc", age: 32 })).not.toThrow();
    expect(friendsRegistry.get("luc")).toEqual({ name: "Luc", age: 32 });
    expect(() => friendsRegistry.add("adrien", { name: 23 })).toThrow();
    expect(() => friendsRegistry.add("hubert", { age: 54 })).toThrow();
    expect(() =>
        friendsRegistry.add("chris", { name: "chris", city: "Namur" }),
    ).toThrow();
    // addValidation is idempotent (first-schema-wins): with the
    // ``globalThis``-anchored shared registry, multiple bundles each inline
    // and re-evaluate the source file that declares the schema, so a second
    // call must be a silent no-op. See registry.js::addValidation.
    expect(() => friendsRegistry.addValidation({ something: Number })).not.toThrow();
    expect(friendsRegistry.validationSchema).toBe(schema);
});

test("can validate by adding a schema after the registry is filled", async () => {
    serverState.debug = "1";
    const schema = { name: String };
    const friendsRegistry = new Registry();
    expect(() => friendsRegistry.add("jean", { name: 999 })).not.toThrow();
    expect(() => friendsRegistry.addValidation(schema)).toThrow();
});

test("can validate subclassess", async () => {
    serverState.debug = "1";
    const schema = { component: { validate: (c) => c.prototype instanceof Component } };
    const widgetRegistry = new Registry();
    widgetRegistry.addValidation(schema);
    class Widget extends Component {}
    expect(() => widgetRegistry.add("calculator", { component: Widget })).not.toThrow({
        message: "Support subclasses",
    });
});

test("function predicate accepts and rejects values", async () => {
    serverState.debug = "1";
    const fnRegistry = new Registry();
    fnRegistry.addValidation((v) => typeof v === "function");

    expect(() => fnRegistry.add("ok", () => 1)).not.toThrow();
    expect(() => fnRegistry.add("bad", { not: "a function" })).toThrow();

    // Only ``=== false`` rejects; truthy / undefined accept.
    /** @type {any} */
    const lenientReg = new Registry();
    lenientReg.addValidation(() => undefined);
    expect(() => lenientReg.add("x", "anything")).not.toThrow();
    expect(() => lenientReg.add("y", null)).not.toThrow();
});

test("function predicate validates existing entries on addValidation", async () => {
    serverState.debug = "1";
    const fnRegistry = new Registry();
    expect(() => fnRegistry.add("good", () => 1)).not.toThrow();
    expect(() => fnRegistry.add("bad", 42)).not.toThrow({
        message: "no schema yet, anything goes",
    });
    // Adding the predicate now retroactively validates the bad entry.
    expect(() =>
        fnRegistry.addValidation((v) => typeof v === "function"),
    ).toThrow();
});

// NOTE: The debug-mode collision warning added to ``Registry.add`` (the
// branch at registry.js:168-176 that fires ``console.warn(...)`` when a
// duplicate key is added with a different value in debug mode) cannot be
// covered here. The Hoot test framework patches
// ``Registry.prototype.add`` in ``static/tests/_framework/module_set.hoot.js``
// to inject ``force: true`` for every call so fixture overrides work;
// that patch bypasses the entire ``if (!force && key in this.content)``
// branch the warning lives in. Out-of-tree verification of the branch:
// ``/tmp/registry_warn_test.mjs`` (inlines the production class and
// exercises the branch under Node).

test("non-debug: warns via console.warn instead of throwing", async () => {
    // 2026-05-07 onward: validation runs in production too, but a failed
    // schema check logs a warning rather than throwing, so a single bad
    // registration cannot crash the page. Throwing remains the dev behavior
    // (covered by the "can validate the values from a schema" test above).
    const schema = { name: String };
    const registry = new Registry();
    registry.addValidation(schema);

    /** @type {any[][]} */
    const warnings = [];
    patchWithCleanup(console, {
        warn: (...args) => warnings.push(args),
    });

    expect(() => registry.add("jean", { name: 50 })).not.toThrow();
    expect(warnings.length).toBe(1);
    expect(warnings[0][0]).toInclude("[registry]");
    expect(warnings[0][0]).toInclude(`Validation error for key "jean"`);
});
