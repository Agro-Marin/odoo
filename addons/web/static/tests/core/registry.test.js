// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { Component } from "@odoo/owl";
import { serverState } from "@web/../tests/web_test_helpers";
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
    expect(() => friendsRegistry.addValidation({ something: Number })).toThrow();
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

test("only validate in debug", async () => {
    const schema = { name: String };
    const registry = new Registry();
    registry.addValidation(schema);
    expect(() => registry.add("jean", { name: 50 })).not.toThrow({
        message: "There is no validation if not in debug mode",
    });
});
