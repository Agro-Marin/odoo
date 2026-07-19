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
    toRawDeep,
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

    test("different key sets with undefined values", () => {
        // Same key COUNT but different key SETS: missing keys read as
        // ``undefined``, which must not compare equal to an explicit
        // ``undefined`` value.
        expect(shallowEqual({ a: undefined }, { b: undefined })).toBe(false);
        expect(shallowEqual({ a: undefined }, { a: undefined })).toBe(true);
        expect(shallowEqual({ a: undefined, b: 1 }, { b: 1, c: undefined })).toBe(
            false,
        );
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

    // primitives, incl. NaN
    expect(deepEqual(1, 1)).toBe(true);
    expect(deepEqual(1, 2)).toBe(false);
    expect(deepEqual(NaN, NaN)).toBe(true);

    // arrays
    expect(deepEqual([1, [2, 3]], [1, [2, 3]])).toBe(true);
    expect(deepEqual([1, 2], [1, 2, 3])).toBe(false);

    // Date / RegExp (no own keys — must compare by value, not be "always equal")
    expect(deepEqual(new Date(2020, 0, 1), new Date(2020, 0, 1))).toBe(true);
    expect(deepEqual(new Date(2020, 0, 1), new Date(2021, 0, 1))).toBe(false);
    expect(deepEqual(/a/gi, /a/gi)).toBe(true);
    expect(deepEqual(/a/g, /a/i)).toBe(false);
    expect(deepEqual(new Date(0), {})).toBe(false);

    // Map / Set
    expect(deepEqual(new Map([[1, 2]]), new Map([[1, 2]]))).toBe(true);
    expect(deepEqual(new Map([[1, 2]]), new Map([[1, 3]]))).toBe(false);
    expect(deepEqual(new Set([1, 2, 3]), new Set([3, 2, 1]))).toBe(true);
    expect(deepEqual(new Set([1, 2]), new Set([1, 9]))).toBe(false);
    // Object elements: matched-element accounting — two elements of one set
    // must not both "consume" the same element of the other, and the
    // relation must be symmetric.
    expect(
        deepEqual(new Set([{ x: 1 }, { x: 1 }]), new Set([{ x: 1 }, { y: 2 }])),
    ).toBe(false);
    expect(
        deepEqual(new Set([{ x: 1 }, { y: 2 }]), new Set([{ x: 1 }, { x: 1 }])),
    ).toBe(false);
    expect(
        deepEqual(new Set([{ x: 1 }, { y: 2 }]), new Set([{ y: 2 }, { x: 1 }])),
    ).toBe(true);

    // cycle-safe (must not stack-overflow)
    const a = { x: 1 };
    a.self = a;
    const b = { x: 1 };
    b.self = b;
    expect(deepEqual(a, b)).toBe(true);

    // divergent cycles: a 1-cycle vs a 2-cycle — one node is compared against
    // two counterpart nodes alternately, so the guard must be keyed on the
    // pair (a single-slot guard flip-flopped and stack-overflowed). Both
    // unfold to {x: {x: {x: ...}}}, hence structurally equal.
    const one = {};
    one.x = one;
    const twoA = {};
    const twoB = { x: twoA };
    twoA.x = twoB;
    expect(deepEqual(one, twoA)).toBe(true);

    // structurally unequal cyclic pairs stay unequal
    const c = { v: 1 };
    c.self = c;
    const d = { v: 2 };
    d.self = d;
    expect(deepEqual(c, d)).toBe(false);
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

    // structuredClone preserves Date, Set, and Map (unlike JSON round-trip).
    // It uses the native Date constructor, so instanceof checks fail when
    // the test runner patches Date with MockDate.
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

    // OWL reactive proxies: structuredClone can't clone Proxy objects (no
    // internal slots), so deepCopy pre-unwraps via toRawDeep before
    // re-attempting structuredClone, preserving Date/Map/Set instead of
    // dropping them via the JSON fallback.
    const reactiveObj = reactive({
        ids: [1, 2, 3],
        name: "test",
        nested: { flag: true },
    });
    const reactiveCopy = deepCopy(reactiveObj);
    expect(reactiveCopy).toEqual({
        ids: [1, 2, 3],
        name: "test",
        nested: { flag: true },
    });
    expect(reactiveCopy).not.toBe(reactiveObj);
    expect(reactiveCopy.ids).not.toBe(reactiveObj.ids);

    // Reproduces the project subtask bug: a plain object containing a reactive
    // array (Many2many field IDs wrapped by OWL reactivity).
    const context = { default_tag_ids: reactive([4, 5, 6]), default_name: "subtask" };
    const contextCopy = deepCopy(context);
    expect(contextCopy).toEqual({
        default_tag_ids: [4, 5, 6],
        default_name: "subtask",
    });
    expect(contextCopy.default_tag_ids).not.toBe(context.default_tag_ids);
});

test("deepCopy preserves structured types through reactive wrapper", () => {
    // Pre-toRawDeep, this fell through to JSON.parse(JSON.stringify(...)) on
    // reactive input, silently mangling Date/Map/Set.
    const date = new Date("2026-05-12T00:00:00Z");
    const set = new Set(["urgent", "billable"]);
    const map = new Map([["k", 1]]);
    const r = reactive({ created: date, tags: set, meta: map });

    const copy = deepCopy(r);

    expect(Object.prototype.toString.call(copy.created)).toBe("[object Date]");
    expect(copy.created.getTime()).toBe(date.getTime());
    expect(copy.created).not.toBe(date);

    expect(copy.tags).toBeInstanceOf(Set);
    expect([...copy.tags].sort()).toEqual(["billable", "urgent"]);

    expect(copy.meta).toBeInstanceOf(Map);
    expect(copy.meta.get("k")).toBe(1);
});

describe("toRawDeep", () => {
    test("returns primitives unchanged", () => {
        expect(toRawDeep(null)).toBe(null);
        expect(toRawDeep(undefined)).toBe(undefined);
        expect(toRawDeep(42)).toBe(42);
        expect(toRawDeep("hello")).toBe("hello");
        expect(toRawDeep(true)).toBe(true);
    });

    test("unwraps reactive objects recursively", () => {
        const target = { a: [{ b: 1 }, { b: 2 }] };
        const r = reactive(target);
        const raw = toRawDeep(r);
        expect(raw).toEqual({ a: [{ b: 1 }, { b: 2 }] });
        expect(raw).not.toBe(r);
        expect(raw.a).not.toBe(r.a);
        expect(raw.a[0]).not.toBe(r.a[0]);
    });

    test("preserves cycles", () => {
        /** @type {any} */
        const a = { name: "a" };
        a.self = a;
        const r = reactive(a);
        const raw = toRawDeep(r);
        expect(raw.name).toBe("a");
        expect(raw.self).toBe(raw);
    });

    test("rebuilds Map and Set", () => {
        const m = new Map([["k", 1]]);
        const s = new Set([1, 2]);
        const r = reactive({ m, s });
        const raw = toRawDeep(r);
        expect(raw.m).toBeInstanceOf(Map);
        expect(raw.m).not.toBe(m);
        expect(raw.m.get("k")).toBe(1);
        expect(raw.s).toBeInstanceOf(Set);
        expect(raw.s).not.toBe(s);
        expect([...raw.s]).toEqual([1, 2]);
    });

    test("passes Date, RegExp by reference", () => {
        // toRawDeep intentionally doesn't clone Date/RegExp — the trailing
        // structuredClone in deepCopy handles that; toRawDeep only needs the
        // slot to be non-reactive.
        const date = new Date();
        const regex = /foo/g;
        const r = reactive({ date, regex });
        const raw = toRawDeep(r);
        expect(raw.date).toBe(date);
        expect(raw.regex).toBe(regex);
    });

    test("supports null-prototype objects", () => {
        const np = Object.create(null);
        np.a = 1;
        const r = reactive({ wrap: np });
        const raw = toRawDeep(r);
        expect(Object.getPrototypeOf(raw.wrap)).toBe(null);
        expect(raw.wrap.a).toBe(1);
    });
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

    // A keyed `undefined` in the extension leaves the target's value intact
    // (same rule as a top-level `undefined` extension), so layering a partial
    // options object with unset fields never wipes the base values.
    expect(deepMerge({ icon: "x", keep: 1 }, { icon: undefined })).toEqual({
        icon: "x",
        keep: 1,
    });
    expect(deepMerge({ a: { b: 2 } }, { a: { b: undefined, c: 3 } })).toEqual({
        a: { b: 2, c: 3 },
    });
    // `null` still overrides (explicit "empty"), unlike `undefined`.
    expect(deepMerge({ a: 1 }, { a: null })).toEqual({ a: null });
});
