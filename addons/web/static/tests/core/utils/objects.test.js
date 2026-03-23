// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { reactive } from "@odoo/owl";
import {
    deepCopy,
    deepEqual,
    deepMerge,
    isObject,
    omit,
    pick,
    shallowEqual,
} from "@web/core/utils/collections/objects";

describe.current.tags("headless");

describe("shallowEqual", () => {
    test("simple valid cases", () => {
        expect(shallowEqual({}, {})).toBe(true);
        expect(shallowEqual({ a: 1 }, { a: 1 })).toBe(true);
        expect(shallowEqual({ a: 1, b: "x" }, { b: "x", a: 1 })).toBe(true);
    });

    test("simple invalid cases", () => {
        expect(shallowEqual({ a: 1 }, { a: 2 })).toBe(false);
        expect(shallowEqual({}, { a: 2 })).toBe(false);
        expect(shallowEqual({ a: 1 }, {})).toBe(false);
    });

    test("objects with non primitive values", () => {
        const obj = { x: "y" };
        expect(shallowEqual({ a: obj }, { a: obj })).toBe(true);
        expect(shallowEqual({ a: { x: "y" } }, { a: { x: "y" } })).toBe(false);

        const arr = ["x", "y", "z"];
        expect(shallowEqual({ a: arr }, { a: arr })).toBe(true);
        expect(shallowEqual({ a: ["x", "y", "z"] }, { a: ["x", "y", "z"] })).toBe(
            false,
        );

        const fn = () => {};
        expect(shallowEqual({ a: fn }, { a: fn })).toBe(true);
        expect(shallowEqual({ a: () => {} }, { a: () => {} })).toBe(false);
    });

    test("custom comparison function", () => {
        const dateA = new Date();
        const dateB = new Date(dateA);

        expect(shallowEqual({ a: 1, date: dateA }, { a: 1, date: dateB })).toBe(false);
        expect(
            shallowEqual({ a: 1, date: dateA }, { a: 1, date: dateB }, (a, b) =>
                a instanceof Date ? Number(a) === Number(b) : a === b,
            ),
        ).toBe(true);
    });
});

test("deepEqual", () => {
    const obj1 = {
        a: ["a", "b", "c"],
        o: {
            b: true,
            n: 10,
        },
    };
    const obj2 = Object.assign({}, obj1);
    const obj3 = Object.assign({}, obj2, { some: "thing" });
    expect(deepEqual(obj1, obj2)).toBe(true);
    expect(deepEqual(obj1, obj3)).toBe(false);
    expect(deepEqual(obj2, obj3)).toBe(false);
});

test("deepCopy", () => {
    const obj = {
        a: ["a", "b", "c"],
        o: {
            b: true,
            n: 10,
        },
    };
    const copy = deepCopy(obj);
    expect(copy).not.toBe(obj);
    expect(copy).toEqual(obj);
    expect(copy.a).not.toBe(obj.a);
    expect(copy.o).not.toBe(obj.o);

    // structuredClone preserves Date, Set, and Map (unlike JSON round-trip)
    // Note: structuredClone uses the native Date constructor, so instanceof
    // checks fail when the test runner patches Date with MockDate.
    const date = new Date();
    const dateCopy = deepCopy(date);
    expect(Object.prototype.toString.call(dateCopy)).toBe("[object Date]");
    expect(dateCopy).not.toBe(date);
    expect(dateCopy.getTime()).toBe(date.getTime());
    expect(typeof dateCopy.getTime).toBe("function");

    const set = new Set(["a"]);
    const setCopy = deepCopy(set);
    expect(setCopy).toBeInstanceOf(Set);
    expect(setCopy).not.toBe(set);
    expect([...setCopy]).toEqual(["a"]);

    const map = new Map([["a", 1]]);
    const mapCopy = deepCopy(map);
    expect(mapCopy).toBeInstanceOf(Map);
    expect(mapCopy).not.toBe(map);
    expect(mapCopy.get("a")).toBe(1);

    // OWL reactive proxies: structuredClone cannot clone Proxy objects (they
    // lack internal slots), so deepCopy falls back to JSON round-trip which
    // reads through the proxy's get trap transparently.
    const reactiveObj = reactive({
        ids: [1, 2, 3],
        name: "test",
        nested: { flag: true },
    });
    const reactiveCopy = deepCopy(reactiveObj);
    expect(reactiveCopy).toEqual({ ids: [1, 2, 3], name: "test", nested: { flag: true } });
    expect(reactiveCopy).not.toBe(reactiveObj);
    expect(reactiveCopy.ids).not.toBe(reactiveObj.ids);

    // Reproduces the project subtask bug: a plain object containing a reactive
    // array (Many2many field IDs wrapped by OWL reactivity).
    const context = { default_tag_ids: reactive([4, 5, 6]), default_name: "subtask" };
    const contextCopy = deepCopy(context);
    expect(contextCopy).toEqual({ default_tag_ids: [4, 5, 6], default_name: "subtask" });
    expect(contextCopy.default_tag_ids).not.toBe(context.default_tag_ids);
});

test("isObject", () => {
    expect(isObject(null)).toBe(false);
    expect(isObject(undefined)).toBe(false);

    expect(isObject("a")).toBe(false);

    expect(isObject(true)).toBe(false);
    expect(isObject(false)).toBe(false);

    expect(isObject(10)).toBe(false);
    expect(isObject(10.01)).toBe(false);

    expect(isObject([])).toBe(false);
    expect(isObject([1, 2])).toBe(false);

    expect(isObject(() => {})).toBe(false);
    expect(isObject(new Set())).toBe(false);
    expect(isObject(new Map())).toBe(false);
    expect(isObject(new Date())).toBe(false);
    expect(isObject(document.body)).toBe(false);
    expect(isObject(new (class AAA extends Array {})())).toBe(false);

    expect(isObject({})).toBe(true);
    expect(isObject({ a: 1 })).toBe(true);
    expect(isObject(Object.create(null))).toBe(true);
    expect(isObject(new (class AAA {})())).toBe(true);
});

test("omit", () => {
    expect(omit({})).toEqual({});
    expect(omit({}, "a")).toEqual({});
    expect(omit({ a: 1 })).toEqual({ a: 1 });
    expect(omit({ a: 1 }, "a")).toEqual({});
    expect(omit({ a: 1, b: 2 }, "c", "a")).toEqual({ b: 2 });
    expect(omit({ a: 1, b: 2 }, "b", "c")).toEqual({ a: 1 });
});

test("pick", () => {
    expect(pick({})).toEqual({});
    expect(pick({}, "a")).toEqual({});
    expect(pick({ a: 3, b: "a", c: [] }, "a")).toEqual({ a: 3 });
    expect(pick({ a: 3, b: "a", c: [] }, "a", "c")).toEqual({ a: 3, c: [] });
    expect(pick({ a: 3, b: "a", c: [] }, "a", "b", "c")).toEqual({
        a: 3,
        b: "a",
        c: [],
    });

    // Non enumerable property
    class MyClass {
        get a() {
            return 1;
        }
    }
    const myClass = new MyClass();
    Object.defineProperty(myClass, "b", { enumerable: false, value: 2 });
    expect(pick(myClass, "a", "b")).toEqual({ a: 1, b: 2 });
});

test("deepMerge", () => {
    expect(
        deepMerge(
            {
                a: 1,
                b: {
                    b_a: 1,
                    b_b: 2,
                },
            },
            {
                a: 2,
                b: {
                    b_b: 3,
                    b_c: 4,
                },
            },
        ),
    ).toEqual({
        a: 2,
        b: {
            b_a: 1,
            b_b: 3,
            b_c: 4,
        },
    });

    expect(deepMerge({}, {})).toEqual({});

    expect(deepMerge({ a: 1 }, {})).toEqual({ a: 1 });
    expect(deepMerge({}, { a: 1 })).toEqual({ a: 1 });
    expect(deepMerge({ a: 1 }, { b: 2 })).toEqual({ a: 1, b: 2 });
    expect(deepMerge({ a: 1 }, { a: 2 })).toEqual({ a: 2 });

    expect(deepMerge(undefined, { a: 1 })).toEqual({ a: 1 });
    expect(deepMerge({ a: 1 }, undefined)).toEqual({ a: 1 });
    expect(deepMerge(undefined, undefined)).toBe(undefined);
    expect(deepMerge({ a: undefined, b: undefined }, { a: { foo: "bar" } })).toEqual({
        a: { foo: "bar" },
        b: undefined,
    });

    expect(deepMerge("foo", 1)).toBe(1);
    expect(deepMerge(null, null)).toBe(null);

    const f = () => {};
    expect(deepMerge({ a: undefined }, { a: f })).toEqual({ a: f });

    // There's no current use for arrays, support can be added if needed
    expect(deepMerge({ a: [1, 2, 3] }, { a: [4] })).toEqual({ a: [4] });

    const symbolA = Symbol("A");
    const symbolB = Symbol("B");
    expect(
        deepMerge(
            {
                [symbolA]: 1,
            },
            {
                [symbolA]: 3,
                [symbolB]: 2,
            },
        ),
    ).toEqual({
        [symbolA]: 3,
        [symbolB]: 2,
    });

    // Extension wins for non-object primitives
    expect(deepMerge(0, 1)).toBe(1);
    expect(deepMerge("a", "b")).toBe("b");
    expect(deepMerge(false, true)).toBe(true);

    // Extension undefined falls back to target
    expect(deepMerge(42, undefined)).toBe(42);
    expect(deepMerge("keep", undefined)).toBe("keep");

    // Nested primitive values are preserved through recursive merge
    expect(deepMerge({ a: { x: 1 } }, { a: { x: 2, y: 3 } })).toEqual({
        a: { x: 2, y: 3 },
    });
});
