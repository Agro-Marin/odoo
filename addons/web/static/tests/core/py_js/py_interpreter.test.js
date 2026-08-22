// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";

describe.current.tags("headless");

const EPS = 1e-9;

describe("basic values", () => {
    test("evaluate simple values", () => {
        expect(evaluateExpr("12")).toBe(12);
        expect(evaluateExpr('"foo"')).toBe("foo");
    });

    test("empty expression", () => {
        expect(() => evaluateExpr("")).toThrow(/Error: Missing token/);
    });

    test("numbers", () => {
        expect(evaluateExpr("1.2")).toBe(1.2);
        expect(evaluateExpr(".12")).toBe(0.12);
        expect(evaluateExpr("0")).toBe(0);
        expect(evaluateExpr("1.0")).toBe(1);
        expect(evaluateExpr("-1.2")).toBe(-1.2);
        expect(evaluateExpr("-12")).toBe(-12);
        expect(evaluateExpr("+12")).toBe(12);
    });

    test("strings", () => {
        expect(evaluateExpr('""')).toBe("");
        expect(evaluateExpr('"foo"')).toBe("foo");
        expect(evaluateExpr("'foo'")).toBe("foo");
        expect(evaluateExpr("'FOO'.lower()")).toBe("foo");
        expect(evaluateExpr("'foo'.upper()")).toBe("FOO");
    });

    test("boolean", () => {
        expect(evaluateExpr("True")).toBe(true);
        expect(evaluateExpr("False")).toBe(false);
    });

    test("lists", () => {
        expect(evaluateExpr("[]")).toEqual([]);
        expect(evaluateExpr("[1]")).toEqual([1]);
        expect(evaluateExpr("[1,2]")).toEqual([1, 2]);
        expect(evaluateExpr("[1,False, None, 'foo']")).toEqual([1, false, null, "foo"]);
        expect(evaluateExpr("[1,2 + 3]")).toEqual([1, 5]);
        expect(evaluateExpr("[1,2, 3][1]")).toBe(2);
    });

    test("None", () => {
        expect(evaluateExpr("None")).toBe(null);
    });

    test("Tuples", () => {
        expect(evaluateExpr("()")).toEqual([]);
        expect(evaluateExpr("(1,)")).toEqual([1]);
        expect(evaluateExpr("(1,2)")).toEqual([1, 2]);
    });

    test("strings can be concatenated", () => {
        expect(evaluateExpr('"foo" + "bar"')).toBe("foobar");
    });
});

describe("number properties", () => {
    test("number arithmetic", () => {
        expect(evaluateExpr("1 + 2")).toBe(3);
        expect(evaluateExpr("4 - 2")).toBe(2);
        expect(evaluateExpr("4 * 2")).toBe(8);
        expect(evaluateExpr("1.5 + 2")).toBe(3.5);
        expect(evaluateExpr("1 + -1")).toBe(0);
        expect(evaluateExpr("1 - 1")).toBe(0);
        expect(evaluateExpr("1.5 - 2")).toBe(-0.5);
        expect(evaluateExpr("0 * 5")).toBe(0);
        expect(evaluateExpr("1 + 3 * 5")).toBe(16);
        expect(evaluateExpr("42 * -2")).toBe(-84);
        expect(evaluateExpr("1 / 2")).toBe(0.5);
        expect(evaluateExpr("2 / 1")).toBe(2);
        expect(evaluateExpr("42 % 5")).toBe(2);
        expect(evaluateExpr("2 ** 3")).toBe(8);
        expect(evaluateExpr("a + b", { a: 1, b: 41 })).toBe(42);
    });

    test("// operator", () => {
        expect(evaluateExpr("1 // 2")).toBe(0);
        expect(evaluateExpr("1 // -2")).toBe(-1);
        expect(evaluateExpr("-1 // 2")).toBe(-1);
        expect(evaluateExpr("6 // 2")).toBe(3);
    });
    test("// on floats floors the true quotient (CPython-verified)", () => {
        expect(evaluateExpr("5 // 0.1")).toBe(49);
        expect(evaluateExpr("1 // 0.1")).toBe(9);
        expect(evaluateExpr("0.5 // 0.1")).toBe(4);
        expect(evaluateExpr("-5 // 0.1")).toBe(-50);
        expect(evaluateExpr("7 // 0.1")).toBe(69);
        expect(evaluateExpr("5 / 0.1")).toBe(50);
        expect(evaluateExpr("5 // -2")).toBe(-3);
        expect(evaluateExpr("-5 // -2")).toBe(2);
    });
});

describe("boolean properties", () => {
    test("boolean arithmetic", () => {
        expect(evaluateExpr("True and False")).toBe(false);
        expect(evaluateExpr("True or False")).toBe(true);
        expect(evaluateExpr("True and (False or True)")).toBe(true);
        expect(evaluateExpr("not True")).toBe(false);
        expect(evaluateExpr("not False")).toBe(true);
        expect(evaluateExpr("not foo", { foo: false })).toBe(true);
        expect(evaluateExpr("not None")).toBe(true);
        expect(evaluateExpr("not []")).toBe(true);
        expect(evaluateExpr("True == False or True == True")).toBe(true);
        expect(evaluateExpr("False == True and False")).toBe(false);
    });

    test("get value from context", () => {
        expect(evaluateExpr("foo == 'foo' or foo == 'bar'", { foo: "bar" })).toBe(true);
        expect(
            evaluateExpr("foo == 'foo' and bar == 'bar'", { foo: "foo", bar: "bar" }),
        ).toBe(true);
    });

    test("should be lazy", () => {
        expect(() =>
            evaluateExpr("foo == 'foo' and bar == 'bar'", { foo: "foo" }),
        ).toThrow();
        expect(evaluateExpr("foo == 'foo' and bar == 'bar'", { foo: "bar" })).toBe(
            false,
        );
        expect(evaluateExpr("foo == 'foo' or bar == 'bar'", { foo: "foo" })).toBe(true);
    });

    test("should return the actual object", () => {
        expect(evaluateExpr('"foo" or "bar"')).toBe("foo");
        expect(evaluateExpr('None or "bar"')).toBe("bar");
        expect(evaluateExpr("False or None")).toBe(null);
        expect(evaluateExpr("0 or 1")).toBe(1);
        expect(evaluateExpr("[] or False")).toBe(false);
    });
});

describe("values from context", () => {
    test("free variable", () => {
        expect(evaluateExpr("a", { a: 3 })).toBe(3);
        expect(evaluateExpr("a + b", { a: 3, b: 5 })).toBe(8);
        expect(evaluateExpr("a", { a: true })).toBe(true);
        expect(evaluateExpr("a", { a: false })).toBe(false);
        expect(evaluateExpr("a", { a: null })).toBe(null);
        expect(evaluateExpr("a", { a: "bar" })).toBe("bar");
        expect(evaluateExpr("foo", { foo: [1, 2, 3] })).toEqual([1, 2, 3]);
    });

    test("special case for context: the eval context can be accessed as 'context'", () => {
        expect(evaluateExpr("context.get('b', 54)", { b: 3 })).toBe(3);
        expect(evaluateExpr("context.get('c', 54)", { b: 3 })).toBe(54);
    });

    test("true and false available in context", () => {
        expect(evaluateExpr("true")).toBe(true);
        expect(evaluateExpr("false")).toBe(false);
    });

    test("throw error if name is not defined", () => {
        expect(() => evaluateExpr("a")).toThrow();
    });
});

describe("comparisons", () => {
    test("equality", () => {
        expect(evaluateExpr("1 == 1")).toBe(true);
        expect(evaluateExpr('"foo" == "foo"')).toBe(true);
        expect(evaluateExpr('"foo" == "bar"')).toBe(false);
        expect(evaluateExpr("1 == True")).toBe(true);
        expect(evaluateExpr("True == 1")).toBe(true);
        expect(evaluateExpr("1 == False")).toBe(false);
        expect(evaluateExpr("False == 1")).toBe(false);
        expect(evaluateExpr("0 == False")).toBe(true);
        expect(evaluateExpr("False == 0")).toBe(true);
        expect(evaluateExpr("None == None")).toBe(true);
        expect(evaluateExpr("None == False")).toBe(false);
    });

    test("equality should work with free variables", () => {
        expect(evaluateExpr("1 == a", { a: 1 })).toBe(true);
        expect(evaluateExpr('foo == "bar"', { foo: "bar" })).toBe(true);
        expect(evaluateExpr('foo == "bar"', { foo: "qux" })).toBe(false);
    });

    test("inequality", () => {
        expect(evaluateExpr("1 != 2")).toBe(true);
        expect(evaluateExpr('"foo" != "foo"')).toBe(false);
        expect(evaluateExpr('"foo" != "bar"')).toBe(true);
    });

    test("inequality should work with free variables", () => {
        expect(evaluateExpr("1 != a", { a: 42 })).toBe(true);
        expect(evaluateExpr('foo != "bar"', { foo: "bar" })).toBe(false);
        expect(evaluateExpr('foo != "bar"', { foo: "qux" })).toBe(true);
        expect(evaluateExpr("foo != bar", { foo: "qux", bar: "quux" })).toBe(true);
    });

    test("should accept deprecated form", () => {
        expect(evaluateExpr("1 <> 2")).toBe(true);
        expect(evaluateExpr('"foo" <> "foo"')).toBe(false);
        expect(evaluateExpr('"foo" <> "bar"')).toBe(true);
    });

    test("comparing numbers", () => {
        expect(evaluateExpr("3 < 5")).toBe(true);
        expect(evaluateExpr("3 > 5")).toBe(false);
        expect(evaluateExpr("5 >= 3")).toBe(true);
        expect(evaluateExpr("3 >= 3")).toBe(true);
        expect(evaluateExpr("3 <= 5")).toBe(true);
        expect(evaluateExpr("5 <= 3")).toBe(false);
    });

    test("should support comparison chains", () => {
        expect(evaluateExpr("1 < 3 < 5")).toBe(true);
        expect(evaluateExpr("5 > 3 > 1")).toBe(true);
        expect(evaluateExpr("1 < 3 > 2 == 2 > -2")).toBe(true);
        expect(evaluateExpr("1 < 2 < 3 < 4 < 5 < 6")).toBe(true);
    });

    test("lists compare lexicographically, not by string coercion", () => {
        expect(evaluateExpr("[2] < [10]")).toBe(true);
        expect(evaluateExpr("[10] < [2]")).toBe(false);
        expect(evaluateExpr("[1, 2] < [1, 3]")).toBe(true);
        expect(evaluateExpr("[1, 2] < [1, 2, 0]")).toBe(true);
        expect(evaluateExpr("[1, 2, 0] < [1, 2]")).toBe(false);
        expect(evaluateExpr("[1, 2] < [1, 2]")).toBe(false);
        expect(evaluateExpr("[2, 0] < [10, 0]")).toBe(true);
        expect(evaluateExpr("[1, 2] >= [1, 2]")).toBe(true);
    });

    test("should compare strings", () => {
        expect(
            evaluateExpr("date >= current", {
                date: "2010-06-08",
                current: "2010-06-05",
            }),
        ).toBe(true);
        expect(evaluateExpr('state >= "cancel"', { state: "cancel" })).toBe(true);
        expect(evaluateExpr('state >= "cancel"', { state: "open" })).toBe(true);
    });

    test("mixed types comparisons", () => {
        expect(evaluateExpr("None < 42")).toBe(true);
        expect(evaluateExpr("None > 42")).toBe(false);
        expect(evaluateExpr("42 > None")).toBe(true);
        expect(evaluateExpr("None < False")).toBe(true);
        expect(evaluateExpr("None < True")).toBe(true);
        expect(evaluateExpr("False > None")).toBe(true);
        expect(evaluateExpr("True > None")).toBe(true);
        expect(evaluateExpr("None > False")).toBe(false);
        expect(evaluateExpr("None > True")).toBe(false);
        expect(evaluateExpr("0 > True")).toBe(false);
        expect(evaluateExpr("0 < True")).toBe(true);
        expect(evaluateExpr("1 <= True")).toBe(true);
        expect(evaluateExpr('False < ""')).toBe(true);
        expect(evaluateExpr('"" > False')).toBe(true);
        expect(evaluateExpr('False > ""')).toBe(false);
        expect(evaluateExpr('0 < ""')).toBe(true);
        expect(evaluateExpr('"" > 0')).toBe(true);
        expect(evaluateExpr('0 > ""')).toBe(false);
        expect(evaluateExpr("3 < True")).toBe(false);
        expect(evaluateExpr("3 > True")).toBe(true);
        expect(evaluateExpr("{} > None")).toBe(true);
        expect(evaluateExpr("{} < None")).toBe(false);
        expect(evaluateExpr("{} > False")).toBe(true);
        expect(evaluateExpr("{} < False")).toBe(false);
        expect(evaluateExpr("3 < 'foo'")).toBe(true);
        expect(evaluateExpr("'foo' < 4444")).toBe(false);
        expect(evaluateExpr("{} < []")).toBe(true);
    });
});

describe("containment", () => {
    test("in tuples", () => {
        expect(evaluateExpr("'bar' in ('foo', 'bar')")).toBe(true);
        expect(evaluateExpr("'bar' in ('foo', 'qux')")).toBe(false);
        expect(evaluateExpr("1 in (1,2,3,4)")).toBe(true);
        expect(evaluateExpr("1 in (2,3,4)")).toBe(false);
        expect(evaluateExpr("'url' in ('url',)")).toBe(true);
        expect(evaluateExpr("'ur' in ('url',)")).toBe(false);
        expect(evaluateExpr("'url' in ('url', 'foo', 'bar')")).toBe(true);
    });

    test("in strings", () => {
        expect(evaluateExpr("'bar' in 'bar'")).toBe(true);
        expect(evaluateExpr("'bar' in 'foobar'")).toBe(true);
        expect(evaluateExpr("'bar' in 'fooqux'")).toBe(false);
    });

    test("in lists", () => {
        expect(evaluateExpr("'bar' in ['foo', 'bar']")).toBe(true);
        expect(evaluateExpr("'bar' in ['foo', 'qux']")).toBe(false);
        expect(evaluateExpr("3  in [1,2,3]")).toBe(true);
        expect(evaluateExpr("None  in [1,'foo',None]")).toBe(true);
        expect(evaluateExpr("not a in b", { a: 3, b: [1, 2, 4, 8] })).toBe(true);
    });

    test("not in", () => {
        expect(evaluateExpr("1  not in (2,3,4)")).toBe(true);
        expect(evaluateExpr('"ur" not in ("url",)')).toBe(true);
        expect(evaluateExpr("-2 not in (1,2,3)")).toBe(true);
        expect(evaluateExpr("-2 not in (1,-2,3)")).toBe(false);
    });

    test("string literals 'not' / 'is' before in/not are not fused into an operator", () => {
        expect(evaluateExpr("'not' in ['not', 'a']")).toBe(true);
        expect(evaluateExpr("'not' in ['a']")).toBe(false);
        expect(evaluateExpr("'is' not in ['a']")).toBe(true);
        expect(evaluateExpr("'is' in ['is']")).toBe(true);
        expect(evaluateExpr("x == 'not' in tags", { x: "not", tags: ["not"] })).toBe(
            true,
        );
    });
});

describe("conversions", () => {
    test("to bool", () => {
        expect(evaluateExpr("bool('')")).toBe(false);
        expect(evaluateExpr("bool('foo')")).toBe(true);
        expect(evaluateExpr("bool(date_deadline)", { date_deadline: "2008" })).toBe(
            true,
        );
        expect(evaluateExpr("bool(s)", { s: "" })).toBe(false);
    });
});

describe("callables", () => {
    test("should not call function from context", () => {
        expect(() => evaluateExpr("foo()", { foo: () => 3 })).toThrow();
        expect(() => evaluateExpr("1 + foo()", { foo: () => 3 })).toThrow();
    });
    test("min/max", () => {
        expect(evaluateExpr("max(3, 5)")).toBe(5);
        expect(evaluateExpr("min(3, 5, 2, 7)")).toBe(2);
    });
    test("min/max over a single iterable argument", () => {
        expect(evaluateExpr("max([1, 5, 2])")).toBe(5);
        expect(evaluateExpr("max(set([1, 2, 3]))")).toBe(3);
        expect(evaluateExpr("min(set([3, 1, 2]))")).toBe(1);
        expect(evaluateExpr("max('abc')")).toBe("c");
        expect(evaluateExpr("max((4, 2))")).toBe(4);
        expect(evaluateExpr("max({'a': 1, 'b': 2})")).toBe("b");
        expect(() => evaluateExpr("max(5)")).toThrow(/not iterable/);
        expect(() => evaluateExpr("max([])")).toThrow(/empty sequence/);
        expect(() => evaluateExpr("min('')")).toThrow(/empty sequence/);
    });
    test("min/max reject unsupported keyword arguments loudly", () => {
        expect(() => evaluateExpr("max([1, 2], default=0)")).toThrow(/not supported/);
        expect(() => evaluateExpr("min([1, 2], default=0)")).toThrow(/not supported/);
    });
});

describe("dicts", () => {
    test("dict", () => {
        expect(evaluateExpr("{}")).toEqual({});
        expect(evaluateExpr("{'foo': 1 + 2}")).toEqual({ foo: 3 });
        expect(evaluateExpr("{'foo': 1, 'bar': 4}")).toEqual({ foo: 1, bar: 4 });
    });

    test("lookup and definition", () => {
        expect(evaluateExpr("{'a': 1}['a']")).toBe(1);
        expect(evaluateExpr("{1: 2}[1]")).toBe(2);
    });

    test("can get values with get method", () => {
        expect(evaluateExpr("{'a': 1}.get('a')")).toBe(1);
        expect(evaluateExpr("{'a': 1}.get('b')")).toBe(null);
        expect(evaluateExpr("{'a': 1}.get('b', 54)")).toBe(54);
    });

    test("can get values from values 'context'", () => {
        expect(evaluateExpr("context.get('a')", { context: { a: 123 } })).toBe(123);
        const values = { context: { a: { b: { c: 321 } } } };
        expect(evaluateExpr("context.get('a').b.c", values)).toBe(321);
        expect(evaluateExpr("context.get('a', {'e': 5}).b.c", values)).toBe(321);
        expect(evaluateExpr("context.get('d', 3)", values)).toBe(3);
        expect(evaluateExpr("context.get('d', {'e': 5})['e']", values)).toBe(5);
    });

    test("can check if a key is in the 'context'", () => {
        expect(evaluateExpr("'a' in context", { context: { a: 123 } })).toBe(true);
        expect(evaluateExpr("'a' in context", { context: { b: 123 } })).toBe(false);
        expect(evaluateExpr("'a' not in context", { context: { a: 123 } })).toBe(false);
        expect(evaluateExpr("'a' not in context", { context: { b: 123 } })).toBe(true);
    });
});

describe("objects", () => {
    test("can read values from object", () => {
        expect(evaluateExpr("obj.a", { obj: { a: 123 } })).toBe(123);
        expect(evaluateExpr("obj.a.b.c", { obj: { a: { b: { c: 321 } } } })).toBe(321);
    });

    test("cannot call function in object", () => {
        expect(() =>
            evaluateExpr("obj.f(3)", {
                obj: { f: (/** @type {number} */ n) => n + 1 },
            }),
        ).toThrow();
    });
});

describe("if expressions", () => {
    test("simple if expressions", () => {
        expect(evaluateExpr("1 if True else 2")).toBe(1);
        expect(evaluateExpr("1 if 3 < 2 else 'greater'")).toBe("greater");
    });

    test("only evaluate proper branch", () => {
        expect(evaluateExpr("1 if True else boom")).toBe(1);
        expect(evaluateExpr("boom if False else 222")).toBe(222);
    });
});

describe("miscellaneous expressions", () => {
    test("tuple in list", () => {
        expect(evaluateExpr("[(1 + 2,'foo', True)]")).toEqual([[3, "foo", true]]);
    });
});

describe("evaluate to boolean", () => {
    test("simple expression", () => {
        expect(evaluateBooleanExpr("12")).toBe(true);
        expect(evaluateBooleanExpr("0")).toBe(false);
        expect(evaluateBooleanExpr("0 + 3 - 1")).toBe(true);
        expect(evaluateBooleanExpr("0 + 3 - 1 - 2")).toBe(false);
        expect(evaluateBooleanExpr('"foo"')).toBe(true);
        expect(evaluateBooleanExpr("[1]")).toBe(true);
        expect(evaluateBooleanExpr("[]")).toBe(false);
    });

    test("use contextual values", () => {
        expect(evaluateBooleanExpr("a", { a: 12 })).toBe(true);
        expect(evaluateBooleanExpr("a", { a: 0 })).toBe(false);
        expect(evaluateBooleanExpr("0 + 3 - a", { a: 1 })).toBe(true);
        expect(evaluateBooleanExpr("0 + 3 - a - 2", { a: 1 })).toBe(false);
        expect(evaluateBooleanExpr("0 + 3 - a - b", { a: 1, b: 2 })).toBe(false);
        expect(evaluateBooleanExpr("a", { a: "foo" })).toBe(true);
        expect(evaluateBooleanExpr("a", { a: [1] })).toBe(true);
        expect(evaluateBooleanExpr("a", { a: [] })).toBe(false);
    });

    test("throw if has missing value", () => {
        expect(() => evaluateBooleanExpr("a", { b: 0 })).toThrow();
        expect(evaluateBooleanExpr("1 or a")).toBe(true);
        expect(() => evaluateBooleanExpr("0 or a")).toThrow();
        expect(() => evaluateBooleanExpr("a or b", { b: true })).toThrow();
        expect(() => evaluateBooleanExpr("a and b", { b: true })).toThrow();
        expect(() => evaluateBooleanExpr("a()")).toThrow();
        expect(() => evaluateBooleanExpr("a[0]")).toThrow();
        expect(() => evaluateBooleanExpr("a.b")).toThrow();
        expect(() => evaluateBooleanExpr("0 + 3 - a", { b: 1 })).toThrow();
        expect(() => evaluateBooleanExpr("0 + 3 - a - 2", { b: 1 })).toThrow();
        expect(() => evaluateBooleanExpr("0 + 3 - a - b", { b: 2 })).toThrow();
    });
});

describe("sets", () => {
    test("static set", () => {
        expect(evaluateExpr("set()")).toEqual(new Set());
        expect(evaluateExpr("set([])")).toEqual(new Set([]));
        expect(evaluateExpr("set([0])")).toEqual(new Set([0]));
        expect(evaluateExpr("set([1])")).toEqual(new Set([1]));
        expect(evaluateExpr("set([0, 0])")).toEqual(new Set([0]));
        expect(evaluateExpr("set([0, 1])")).toEqual(new Set([0, 1]));
        expect(evaluateExpr("set([1, 1])")).toEqual(new Set([1]));

        expect(evaluateExpr("set('')")).toEqual(new Set());
        expect(evaluateExpr("set('a')")).toEqual(new Set(["a"]));
        expect(evaluateExpr("set('ab')")).toEqual(new Set(["a", "b"]));

        expect(evaluateExpr("set({})")).toEqual(new Set());
        expect(evaluateExpr("set({ 'a': 1 })")).toEqual(new Set(["a"]));
        expect(evaluateExpr("set({ '': 1, 'a': 1 })")).toEqual(new Set(["", "a"]));

        expect(() => evaluateExpr("set(0)")).toThrow();
        expect(() => evaluateExpr("set(1)")).toThrow();
        expect(() => evaluateExpr("set(None)")).toThrow();
        expect(() => evaluateExpr("set(false)")).toThrow();
        expect(() => evaluateExpr("set(true)")).toThrow();
        expect(() => evaluateExpr("set(1, 2)")).toThrow();

        expect(() => evaluateExpr("set(expr)", { expr: undefined })).toThrow();
        expect(() => evaluateExpr("set(expr)", { expr: null })).toThrow();

        expect(() => evaluateExpr("set([], [])")).toThrow();
        expect(() => evaluateExpr("set({ 'a' })")).toThrow();
    });

    test("set intersection", () => {
        expect(evaluateExpr("set([1,2,3]).intersection()")).toEqual(new Set([1, 2, 3]));
        expect(evaluateExpr("set([1,2,3]).intersection(set([2,3]))")).toEqual(
            new Set([2, 3]),
        );
        expect(evaluateExpr("set([1,2,3]).intersection([2,3])")).toEqual(
            new Set([2, 3]),
        );
        expect(evaluateExpr("set([1,2,3]).intersection(r)", { r: [2, 3] })).toEqual(
            new Set([2, 3]),
        );
        expect(
            evaluateExpr("r.intersection([2,3])", { r: new Set([1, 2, 3, 2]) }),
        ).toEqual(new Set([2, 3]));

        expect(
            evaluateExpr("set(foo_ids).intersection([2,3])", { foo_ids: [1, 2] }),
        ).toEqual(new Set([2]));
        expect(
            evaluateExpr("set(foo_ids).intersection([2,3])", { foo_ids: [1] }),
        ).toEqual(new Set());
        expect(
            evaluateExpr("set([foo_id]).intersection([2,3])", { foo_id: 1 }),
        ).toEqual(new Set());
        expect(
            evaluateExpr("set([foo_id]).intersection([2,3])", { foo_id: 2 }),
        ).toEqual(new Set([2]));

        expect(() => evaluateExpr("set([]).intersection([], [])")).toThrow();
        expect(() => evaluateExpr("set([]).intersection([], [], [])")).toThrow();
    });

    test("set difference", () => {
        expect(evaluateExpr("set([1,2,3]).difference()")).toEqual(new Set([1, 2, 3]));
        expect(evaluateExpr("set([1,2,3]).difference(set([2,3]))")).toEqual(
            new Set([1]),
        );
        expect(evaluateExpr("set([1,2,3]).difference([2,3])")).toEqual(new Set([1]));
        expect(evaluateExpr("set([1,2,3]).difference(r)", { r: [2, 3] })).toEqual(
            new Set([1]),
        );
        expect(
            evaluateExpr("r.difference([2,3])", { r: new Set([1, 2, 3, 2, 4]) }),
        ).toEqual(new Set([1, 4]));

        expect(
            evaluateExpr("set(foo_ids).difference([2,3])", { foo_ids: [1, 2] }),
        ).toEqual(new Set([1]));
        expect(
            evaluateExpr("set(foo_ids).difference([2,3])", { foo_ids: [1] }),
        ).toEqual(new Set([1]));
        expect(evaluateExpr("set([foo_id]).difference([2,3])", { foo_id: 1 })).toEqual(
            new Set([1]),
        );
        expect(evaluateExpr("set([foo_id]).difference([2,3])", { foo_id: 2 })).toEqual(
            new Set(),
        );

        expect(() => evaluateExpr("set([]).difference([], [])")).toThrow();
        expect(() => evaluateExpr("set([]).difference([], [], [])")).toThrow();
    });

    test("set union", () => {
        expect(evaluateExpr("set([1,2,3]).union()")).toEqual(new Set([1, 2, 3]));
        expect(evaluateExpr("set([1,2,3]).union(set([2,3,4]))")).toEqual(
            new Set([1, 2, 3, 4]),
        );
        expect(evaluateExpr("set([1,2,3]).union([2,4])")).toEqual(
            new Set([1, 2, 3, 4]),
        );
        expect(evaluateExpr("set([1,2,3]).union(r)", { r: [2, 4] })).toEqual(
            new Set([1, 2, 3, 4]),
        );
        expect(evaluateExpr("r.union([2,3])", { r: new Set([1, 2, 2, 4]) })).toEqual(
            new Set([1, 2, 4, 3]),
        );

        expect(evaluateExpr("set(foo_ids).union([2,3])", { foo_ids: [1, 2] })).toEqual(
            new Set([1, 2, 3]),
        );
        expect(evaluateExpr("set(foo_ids).union([2,3])", { foo_ids: [1] })).toEqual(
            new Set([1, 2, 3]),
        );
        expect(evaluateExpr("set([foo_id]).union([2,3])", { foo_id: 1 })).toEqual(
            new Set([1, 2, 3]),
        );
        expect(evaluateExpr("set([foo_id]).union([2,3])", { foo_id: 2 })).toEqual(
            new Set([2, 3]),
        );

        expect(() => evaluateExpr("set([]).union([], [])")).toThrow();
        expect(() => evaluateExpr("set([]).union([], [], [])")).toThrow();
    });
});

describe("builtins — len", () => {
    test("len of list", () => {
        expect(evaluateExpr("len([1, 2, 3])")).toBe(3);
        expect(evaluateExpr("len([])")).toBe(0);
    });
    test("len of string", () => {
        expect(evaluateExpr('len("hello")')).toBe(5);
        expect(evaluateExpr('len("")')).toBe(0);
    });
    test("len of dict", () => {
        expect(evaluateExpr("len({'a': 1, 'b': 2})")).toBe(2);
    });
    test("len of set", () => {
        expect(evaluateExpr("len(set([1, 2, 3]))")).toBe(3);
    });
    test("len of non-collection throws", () => {
        expect(() => evaluateExpr("len(42)")).toThrow();
    });
});

describe("builtins — abs", () => {
    test("abs of positive", () => {
        expect(evaluateExpr("abs(5)")).toBe(5);
    });
    test("abs of negative", () => {
        expect(evaluateExpr("abs(-5)")).toBe(5);
    });
    test("abs of zero", () => {
        expect(evaluateExpr("abs(0)")).toBe(0);
    });
    test("abs of float", () => {
        expect(evaluateExpr("abs(-3.14)")).toBeCloseTo(3.14, { margin: EPS });
    });
    test("abs of negative timedelta", () => {
        const result = evaluateExpr("abs(datetime.timedelta(days=-5))");
        expect(result.days).toBe(5);
        expect(result.seconds).toBe(0);
    });
    test("abs of positive timedelta is unchanged", () => {
        const result = evaluateExpr("abs(datetime.timedelta(days=3))");
        expect(result.days).toBe(3);
    });
    test("abs of zero timedelta", () => {
        const result = evaluateExpr("abs(datetime.timedelta(days=0))");
        expect(result.days).toBe(0);
    });
});

describe("builtins — int", () => {
    test("int from string", () => {
        expect(evaluateExpr('int("42")')).toBe(42);
        expect(evaluateExpr('int("-7")')).toBe(-7);
        expect(evaluateExpr('int("+3")')).toBe(3);
    });
    test("int from float (truncates toward zero)", () => {
        expect(evaluateExpr("int(3.9)")).toBe(3);
        expect(evaluateExpr("int(-3.9)")).toBe(-3);
    });
    test("int with explicit base", () => {
        expect(evaluateExpr("int('10', 2)")).toBe(2);
        expect(evaluateExpr("int('777', 8)")).toBe(511);
        expect(evaluateExpr("int('ff', 16)")).toBe(255);
        expect(evaluateExpr("int('FF', 16)")).toBe(255);
        expect(evaluateExpr("int('0x10', 16)")).toBe(16);
        expect(evaluateExpr("int('z', 36)")).toBe(35);
        expect(evaluateExpr("int('ff', base=16)")).toBe(255);
    });
    test("int base 0 auto-detects the prefix", () => {
        expect(evaluateExpr("int('0x1f', 0)")).toBe(31);
        expect(evaluateExpr("int('0o17', 0)")).toBe(15);
        expect(evaluateExpr("int('0b101', 0)")).toBe(5);
        expect(evaluateExpr("int('42', 0)")).toBe(42);
        expect(evaluateExpr("int('0', 0)")).toBe(0);
        expect(() => evaluateExpr("int('010', 0)")).toThrow(/invalid literal/);
    });
    test("int accepts PEP 515 underscores", () => {
        expect(evaluateExpr("int('1_000')")).toBe(1000);
        expect(evaluateExpr("int('0x_1f', 16)")).toBe(31);
        expect(() => evaluateExpr("int('1__0')")).toThrow(/invalid literal/);
        expect(() => evaluateExpr("int('_1')")).toThrow(/invalid literal/);
    });
    test("int with base rejects bad base / non-string value", () => {
        expect(() => evaluateExpr("int('10', 1)")).toThrow(/base must be/);
        expect(() => evaluateExpr("int('10', 37)")).toThrow(/base must be/);
        expect(() => evaluateExpr("int(5, 2)")).toThrow(
            /non-string with explicit base/,
        );
        expect(() => evaluateExpr("int('ff', 10)")).toThrow(/invalid literal/);
    });
    test("int from boolean", () => {
        expect(evaluateExpr("int(True)")).toBe(1);
        expect(evaluateExpr("int(False)")).toBe(0);
    });
    test("int rejects non-integer strings", () => {
        expect(() => evaluateExpr('int("42abc")')).toThrow(/invalid literal/);
        expect(() => evaluateExpr('int("abc")')).toThrow(/invalid literal/);
        expect(() => evaluateExpr('int("")')).toThrow(/invalid literal/);
    });
    test("int rejects non-numeric objects (Python TypeError)", () => {
        expect(() => evaluateExpr("int(None)")).toThrow(/int\(\) argument/);
        expect(() => evaluateExpr("int([])")).toThrow(/int\(\) argument/);
        expect(() => evaluateExpr("int({})")).toThrow(/int\(\) argument/);
    });
});

describe("builtins — float", () => {
    test("float from string", () => {
        expect(evaluateExpr('float("3.14")')).toBeCloseTo(3.14, { margin: EPS });
        expect(evaluateExpr('float("-2.5")')).toBe(-2.5);
    });
    test("float from int", () => {
        expect(evaluateExpr("float(42)")).toBe(42);
    });
    test("float from boolean", () => {
        expect(evaluateExpr("float(True)")).toBe(1.0);
        expect(evaluateExpr("float(False)")).toBe(0.0);
    });
    test("float rejects empty string", () => {
        expect(() => evaluateExpr('float("")')).toThrow(/could not convert/);
    });
    test("float rejects non-numeric string", () => {
        expect(() => evaluateExpr('float("abc")')).toThrow(/could not convert/);
    });
    test("float rejects non-numeric objects (Python TypeError)", () => {
        expect(() => evaluateExpr("float(None)")).toThrow(/float\(\) argument/);
        expect(() => evaluateExpr("float([])")).toThrow(/float\(\) argument/);
    });

    test("float accepts PEP 515 underscores, exactly where CPython does", () => {
        expect(evaluateExpr('float("1_000")')).toBe(1000);
        expect(evaluateExpr('float("1_000.5")')).toBe(1000.5);
        expect(evaluateExpr('float("1.000_1")')).toBe(1.0001);
        expect(evaluateExpr('float("1_0e1_0")')).toBe(1e11);
        expect(evaluateExpr('float(".5_1")')).toBe(0.51);
        expect(evaluateExpr('float("1_000_000")')).toBe(1000000);
        expect(evaluateExpr('float("0_1")')).toBe(1);
        expect(evaluateExpr('float("-1_0.5_5")')).toBe(-10.55);
        expect(evaluateExpr('float("+1_0")')).toBe(10);
        expect(evaluateExpr('float(" 1_0 ")')).toBe(10);
        expect(evaluateExpr('float("1.2_3e4_5")')).toBe(1.23e45);
        expect(evaluateExpr('float("1_0.")')).toBe(10);
        expect(evaluateExpr('float(".1_2")')).toBe(0.12);
    });

    test("float rejects an underscore that is not between two digits", () => {
        for (const bad of [
            "1_",
            "_1",
            "1__0",
            "1_.5",
            "1._5",
            "1e_5",
            "1_e5",
            "1.5_",
            "_",
        ]) {
            expect(() => evaluateExpr(`float("${bad}")`)).toThrow(/could not convert/, {
                message: `float("${bad}")`,
            });
        }
    });

    test("float rejects radix prefixes, which only int() takes", () => {
        expect(() => evaluateExpr('float("0x10")')).toThrow(/could not convert/);
        expect(() => evaluateExpr('float("0b11")')).toThrow(/could not convert/);
        expect(() => evaluateExpr('float("0o7")')).toThrow(/could not convert/);
        expect(evaluateExpr('int("0x10", 16)')).toBe(16);
    });

    test("float still accepts the rest of Python's float grammar", () => {
        expect(evaluateExpr('float("1.")')).toBe(1);
        expect(evaluateExpr('float("1e5")')).toBe(100000);
        expect(evaluateExpr('float("inf")')).toBe(Infinity);
        expect(evaluateExpr('float("-inf")')).toBe(-Infinity);
        expect(evaluateExpr('float("Infinity")')).toBe(Infinity);
        expect(Number.isNaN(evaluateExpr('float("nan")'))).toBe(true);
        expect(() => evaluateExpr('float("1d")')).toThrow(/could not convert/);
    });
});

describe("builtins — sorted", () => {
    test("sorts lists, strings, sets and dict keys like CPython", () => {
        expect(evaluateExpr("sorted([3, 1, 2])")).toEqual([1, 2, 3]);
        expect(evaluateExpr('sorted("cba")')).toEqual(["a", "b", "c"]);
        expect(evaluateExpr("sorted(set([3, 1, 2]))")).toEqual([1, 2, 3]);
        expect(evaluateExpr("sorted({'b': 1, 'a': 2})")).toEqual(["a", "b"]);
        expect(evaluateExpr("sorted([])")).toEqual([]);
    });

    test("reverse= honoured; the source list is not mutated", () => {
        expect(evaluateExpr("sorted([3, 1, 2], reverse=True)")).toEqual([3, 2, 1]);
        expect(evaluateExpr("sorted([3, 1, 2], reverse=False)")).toEqual([1, 2, 3]);
        expect(evaluateExpr("[sorted(l), l]", { l: [3, 1, 2] })).toEqual([
            [1, 2, 3],
            [3, 1, 2],
        ]);
    });

    test("key= raises instead of silently returning a differently-sorted list", () => {
        expect(() => evaluateExpr("sorted([1, 2], key=1)")).toThrow(
            /keyword arguments \(key\) are not supported/,
        );
    });

    test("non-iterable raises", () => {
        expect(() => evaluateExpr("sorted(1)")).toThrow(/not iterable/);
    });
});

describe("builtins — repr", () => {
    test("repr matches CPython for the values py_js can hold", () => {
        expect(evaluateExpr(`repr("it's")`)).toBe(`"it's"`);
        expect(evaluateExpr('repr("a")')).toBe("'a'");
        expect(evaluateExpr('repr([1, "a"])')).toBe(`[1, 'a']`);
        expect(evaluateExpr("repr({'a': 1})")).toBe(`{'a': 1}`);
        expect(evaluateExpr("repr(True)")).toBe("True");
        expect(evaluateExpr("repr(None)")).toBe("None");
        expect(evaluateExpr("repr(set([1]))")).toBe("{1}");
    });
});

describe("error messages use Python type names, not JS class names", () => {
    test("dict and set", () => {
        expect(() => evaluateExpr("abs({})")).toThrow(
            /bad operand type for abs\(\): 'dict'/,
        );
        expect(() => evaluateExpr("abs(set([1]))")).toThrow(
            /bad operand type for abs\(\): 'set'/,
        );
        expect(() => evaluateExpr("1 + {}")).toThrow(/'int' and 'dict'/);
        expect(() => evaluateExpr("1 + set([1])")).toThrow(/'int' and 'set'/);
    });

    test("int and float, from len()", () => {
        expect(() => evaluateExpr("len(42)")).toThrow(
            /object of type 'int' has no len\(\)/,
        );
        expect(() => evaluateExpr("len(1.5)")).toThrow(
            /object of type 'float' has no len\(\)/,
        );
    });

    test("temporals report their Python names", () => {
        expect(() =>
            evaluateExpr("datetime.time(1, 0, 0) < datetime.date(2020, 1, 1)"),
        ).toThrow(/'time' and 'date'/);
    });
});

describe("builtins — str", () => {
    test("str from number", () => {
        expect(evaluateExpr("str(42)")).toBe("42");
        expect(evaluateExpr("str(3.14)")).toBe("3.14");
    });
    test("str from boolean", () => {
        expect(evaluateExpr("str(True)")).toBe("True");
        expect(evaluateExpr("str(False)")).toBe("False");
    });
    test("str from None", () => {
        expect(evaluateExpr("str(None)")).toBe("None");
    });
    test("str of a float-valued integer diverges from Python (documented)", () => {
        expect(evaluateExpr("str(1.0)")).toBe("1");
    });
});

describe("builtins — round", () => {
    test("round to integer", () => {
        expect(evaluateExpr("round(3.7)")).toBe(4);
        expect(evaluateExpr("round(3.2)")).toBe(3);
    });
    test("round with ndigits", () => {
        expect(evaluateExpr("round(3.14159, 2)")).toBeCloseTo(3.14, { margin: EPS });
        expect(evaluateExpr("round(1234.5, -2)")).toBe(1200);
    });
    test("round uses banker's rounding (half-to-even)", () => {
        expect(evaluateExpr("round(0.5)")).toBe(0);
        expect(evaluateExpr("round(1.5)")).toBe(2);
        expect(evaluateExpr("round(2.5)")).toBe(2);
        expect(evaluateExpr("round(3.5)")).toBe(4);
    });
    test("round negative half-to-even", () => {
        expect(evaluateExpr("round(-0.5)")).toBe(0);
        expect(evaluateExpr("round(-1.5)")).toBe(-2);
        expect(evaluateExpr("round(-2.5)")).toBe(-2);
    });
    test("round matches Python IEEE-754 behaviour for ndigits > 0", () => {
        expect(evaluateExpr("round(2.675, 2)")).toBeCloseTo(2.67, { margin: EPS });
        expect(evaluateExpr("round(0.45, 1)")).toBeCloseTo(0.5, { margin: EPS });
        expect(evaluateExpr("round(0.35, 1)")).toBeCloseTo(0.3, { margin: EPS });
        expect(evaluateExpr("round(0.25, 1)")).toBeCloseTo(0.2, { margin: EPS });
        expect(evaluateExpr("round(0.15, 1)")).toBeCloseTo(0.1, { margin: EPS });
    });
    test("round with negative ndigits", () => {
        expect(evaluateExpr("round(150, -2)")).toBe(200);
        expect(evaluateExpr("round(250, -2)")).toBe(200);
    });
});

describe("security — blocked properties", () => {
    test("bracket access to constructor is blocked", () => {
        expect(() => evaluateExpr('a["constructor"]', { a: {} })).toThrow(/forbidden/);
    });
    test("bracket access to __proto__ is blocked", () => {
        expect(() => evaluateExpr('a["__proto__"]', { a: {} })).toThrow(/forbidden/);
    });
    test("bracket access to prototype is blocked", () => {
        expect(() => evaluateExpr('a["prototype"]', { a: {} })).toThrow(/forbidden/);
    });
    test("dot access to constructor is blocked", () => {
        expect(() => evaluateExpr("a.constructor", { a: {} })).toThrow(/forbidden/);
    });
    test("dot access to __proto__ is blocked", () => {
        expect(() => evaluateExpr("a.__proto__", { a: {} })).toThrow(/forbidden/);
    });
    test("legitimate property access still works", () => {
        expect(evaluateExpr("a.name", { a: { name: "test" } })).toBe("test");
        expect(evaluateExpr('a["name"]', { a: { name: "test" } })).toBe("test");
    });
});

describe("security — recursion depth limit", () => {
    test("deeply nested expression throws", () => {
        const depth = 250;
        const expr = "True and ".repeat(depth) + "1";
        expect(() => evaluateExpr(expr)).toThrow(/depth/i);
    });

    test("long chains within the parser depth limit still evaluate", () => {
        const expr = "1" + " + 1".repeat(150);
        expect(evaluateExpr(expr)).toBe(151);
    });
});

describe("operators — is / is not", () => {
    test("is None", () => {
        expect(evaluateExpr("x is None", { x: null })).toBe(true);
        expect(evaluateExpr("x is None", { x: 0 })).toBe(false);
        expect(evaluateExpr("x is None", { x: "" })).toBe(false);
    });
    test("is not None", () => {
        expect(evaluateExpr("x is not None", { x: null })).toBe(false);
        expect(evaluateExpr("x is not None", { x: 42 })).toBe(true);
    });
});

describe("operators — division by zero", () => {
    test("/ by zero throws", () => {
        expect(() => evaluateExpr("1 / 0")).toThrow(/ZeroDivisionError/);
    });
    test("% by zero throws", () => {
        expect(() => evaluateExpr("5 % 0")).toThrow(/ZeroDivisionError/);
    });
    test("// by zero throws", () => {
        expect(() => evaluateExpr("5 // 0")).toThrow(/ZeroDivisionError/);
    });
    test("non-zero division works", () => {
        expect(evaluateExpr("10 / 3")).toBeCloseTo(3.333, { margin: 1e-3 });
        expect(evaluateExpr("10 % 3")).toBe(1);
        expect(evaluateExpr("10 // 3")).toBe(3);
    });
});

describe("operators — bitwise", () => {
    test("bitwise or", () => {
        expect(evaluateExpr("5 | 3")).toBe(7);
    });
    test("bitwise and", () => {
        expect(evaluateExpr("5 & 3")).toBe(1);
    });
    test("bitwise xor", () => {
        expect(evaluateExpr("5 ^ 3")).toBe(6);
    });
    test("bitwise not", () => {
        expect(evaluateExpr("~0")).toBe(-1);
        expect(evaluateExpr("~5")).toBe(-6);
        expect(evaluateExpr("~-1")).toBe(0);
        expect(evaluateExpr("~5000000000")).toBe(-5000000001);
        expect(evaluateExpr("~2147483648")).toBe(-2147483649);
    });
    test("bitwise not is integer-only (Python TypeError on float)", () => {
        expect(() => evaluateExpr("~2.5")).toThrow(/bad operand type for unary ~/);
    });
    test("left shift", () => {
        expect(evaluateExpr("1 << 3")).toBe(8);
    });
    test("right shift", () => {
        expect(evaluateExpr("8 >> 2")).toBe(2);
    });
    test("bitwise/shift operators reject non-integers (Python TypeError)", () => {
        expect(() => evaluateExpr("'a' | 1")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("1.5 & 2")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("1.5 << 1")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("None ^ 1")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("[] >> 1")).toThrow(/unsupported operand/);
        expect(evaluateExpr("True | 2")).toBe(3);
        expect(evaluateExpr("True << 2")).toBe(4);
    });
});

describe("in operator — Object.hasOwn", () => {
    test("'in' checks own properties only (not prototype)", () => {
        expect(evaluateExpr('"toString" in a', { a: {} })).toBe(false);
        expect(evaluateExpr('"toString" in a', { a: { toString: 1 } })).toBe(true);
    });
    test("'in' works for Set membership", () => {
        expect(evaluateExpr("1 in s", { s: new Set([1, 2, 3]) })).toBe(true);
        expect(evaluateExpr("4 in s", { s: new Set([1, 2, 3]) })).toBe(false);
    });
});

describe("Python semantics fixes", () => {
    test("negative indexing on lists (Python lst[-1])", () => {
        expect(evaluateExpr("[1, 2, 3][-1]")).toBe(3);
        expect(evaluateExpr("[1, 2, 3][-2]")).toBe(2);
        expect(evaluateExpr("[1, 2, 3][-3]")).toBe(1);
        expect(evaluateExpr("[1, 2, 3][0]")).toBe(1);
        expect(evaluateExpr("[1, 2, 3][2]")).toBe(3);
    });

    test("negative indexing on strings (Python s[-1])", () => {
        expect(evaluateExpr("'abc'[-1]")).toBe("c");
        expect(evaluateExpr("'abc'[-2]")).toBe("b");
        expect(evaluateExpr("'abc'[0]")).toBe("a");
    });

    test("str * int and list * int repetition", () => {
        expect(evaluateExpr("'ab' * 2")).toBe("abab");
        expect(evaluateExpr("2 * 'ab'")).toBe("abab");
        expect(evaluateExpr("'ab' * 0")).toBe("");
        expect(evaluateExpr("[1] * 3")).toEqual([1, 1, 1]);
        expect(evaluateExpr("3 * [1, 2]")).toEqual([1, 2, 1, 2, 1, 2]);
        expect(evaluateExpr("3 * 4")).toBe(12);
    });

    test("'%' string formatting", () => {
        expect(evaluateExpr("'%s' % 5")).toBe("5");
        expect(evaluateExpr("'%s and %s' % (1, 2)")).toBe("1 and 2");
        expect(evaluateExpr("'%d apples' % 3")).toBe("3 apples");
        expect(evaluateExpr("'%s' % 'x'")).toBe("x");
        expect(evaluateExpr("'%(name)s' % {'name': 'foo'}")).toBe("foo");
        expect(evaluateExpr("7 % 3")).toBe(1);
    });
    test("'%' formatting flags, width and precision (CPython-verified)", () => {
        expect(evaluateExpr("'%05d' % -3")).toBe("-0003");
        expect(evaluateExpr("'%05d' % 3")).toBe("00003");
        expect(evaluateExpr("'%05.1f' % -3.5")).toBe("-03.5");
        expect(evaluateExpr("'%05s' % 3")).toBe("    3");
        expect(evaluateExpr("'%-5d' % 3 + '|'")).toBe("3    |");
        expect(evaluateExpr("'%5d' % -3")).toBe("   -3");
        expect(evaluateExpr("'%e' % 123.456")).toBe("1.234560e+02");
        expect(evaluateExpr("'%.2e' % 0.000123")).toBe("1.23e-04");
        expect(evaluateExpr("'%E' % 12")).toBe("1.200000E+01");
        expect(evaluateExpr("'%.0e' % 5")).toBe("5e+00");
        expect(evaluateExpr("'%10.2e' % -3.5")).toBe(" -3.50e+00");
        expect(evaluateExpr("'%.2g' % 123.456")).toBe("1.2e+02");
        expect(evaluateExpr("'%g' % 1234567.0")).toBe("1.23457e+06");
        expect(evaluateExpr("'%g' % 0.0001")).toBe("0.0001");
        expect(evaluateExpr("'%g' % 0.00001")).toBe("1e-05");
        expect(evaluateExpr("'%.3g' % 0.000123456")).toBe("0.000123");
        expect(evaluateExpr("'%g' % 100")).toBe("100");
        expect(evaluateExpr("'%g' % 1.5")).toBe("1.5");
        expect(evaluateExpr("'%.0g' % 123")).toBe("1e+02");
        expect(evaluateExpr("'%x' % 255")).toBe("ff");
        expect(evaluateExpr("'%X' % 255")).toBe("FF");
        expect(evaluateExpr("'%o' % 8")).toBe("10");
    });
    test("'%' precision on strings truncates (CPython-verified)", () => {
        expect(evaluateExpr("'%.3s' % 'hello'")).toBe("hel");
        expect(evaluateExpr("'%.3r' % 'hello'")).toBe("'he");
        expect(evaluateExpr("'%.10s' % 'hi'")).toBe("hi");
        expect(evaluateExpr("'%-5.3s' % 'hello' + '|'")).toBe("hel  |");
    });
    test("'%' precision on integers is a minimum digit count (CPython-verified)", () => {
        expect(evaluateExpr("'%.3d' % 5")).toBe("005");
        expect(evaluateExpr("'%.4x' % 255")).toBe("00ff");
        expect(evaluateExpr("'%.4X' % 255")).toBe("00FF");
        expect(evaluateExpr("'%+.3d' % 5")).toBe("+005");
        expect(evaluateExpr("'%.0d' % 0")).toBe("0");
    });
    test("'%' alternate form (#) places the prefix after the sign (CPython-verified)", () => {
        expect(evaluateExpr("'%#x' % 255")).toBe("0xff");
        expect(evaluateExpr("'%#x' % -255")).toBe("-0xff");
        expect(evaluateExpr("'%#o' % -8")).toBe("-0o10");
        expect(evaluateExpr("'%#x' % 0")).toBe("0x0");
        expect(evaluateExpr("'%#06x' % 255")).toBe("0x00ff");
        expect(evaluateExpr("'%-#8x' % 255")).toBe("0xff    ");
    });
    test("'%f' uses round-half-to-even like CPython", () => {
        expect(evaluateExpr("'%.0f' % 2.5")).toBe("2");
        expect(evaluateExpr("'%.0f' % 0.5")).toBe("0");
        expect(evaluateExpr("'%.0f' % 1.5")).toBe("2");
        expect(evaluateExpr("'%.0f' % 3.5")).toBe("4");
        expect(evaluateExpr("'%.0f' % -2.5")).toBe("-2");
        expect(evaluateExpr("'%.2f' % 2.675")).toBe("2.67");
    });

    test("'%' formatting mapping and argument errors", () => {
        expect(() => evaluateExpr("'%(b)s' % {'a': 1}")).toThrow(/KeyError: 'b'/);
        expect(() => evaluateExpr("'%(a)s' % [1, 2]")).toThrow(
            /format requires a mapping/,
        );
        expect(() => evaluateExpr("'%s %s' % 5")).toThrow(/not enough arguments/);
    });

    test("'%' formatting accepts every py_js spelling of a dict as a mapping", () => {
        expect(evaluateExpr("'%(a)s' % {'a': 1}")).toBe("1");
        expect(evaluateExpr("'%(a)s' % d", { d: { a: 1 } })).toBe("1");
        expect(evaluateExpr("'%(lang)s' % context", { lang: "en_US" })).toBe("en_US");
        expect(
            evaluateExpr("'%(lang)s/%(tz)s' % context", { lang: "fr_BE", tz: "UTC" }),
        ).toBe("fr_BE/UTC");
        expect(evaluateExpr("'%(a)s' % context", { context: { a: 7 } })).toBe("7");
        expect(() => evaluateExpr("'%(nope)s' % context", { lang: "en_US" })).toThrow(
            /KeyError: 'nope'/,
        );
    });

    test("'%' formatting still rejects a non-dict operand as a mapping", () => {
        expect(() => evaluateExpr("'%(a)s' % datetime.date(2020, 1, 1)")).toThrow(
            /format requires a mapping/,
        );
        expect(() => evaluateExpr("'' % datetime.date(2020, 1, 1)")).toThrow(
            /not all arguments converted/,
        );
    });

    test("'%' formatting distinguishes a tuple operand from a list operand", () => {
        expect(evaluateExpr("'%s' % [1, 2]")).toBe("[1, 2]");
        expect(evaluateExpr("'%s and %s' % (1, 2)")).toBe("1 and 2");
        expect(() => evaluateExpr("'%s %s' % [1, 2]")).toThrow(/not enough arguments/);
        expect(evaluateExpr("'%s|%s' % ([1, 2], 3)")).toBe("[1, 2]|3");
        expect(evaluateExpr("(1, 2)")).toEqual([1, 2]);
        expect(evaluateExpr("(1, 2) + [3]")).toEqual([1, 2, 3]);
    });

    test("'%' formatting raises when arguments are left over (Python TypeError)", () => {
        expect(() => evaluateExpr("'%s' % (1, 2)")).toThrow(
            /not all arguments converted/,
        );
        expect(() => evaluateExpr("'abc' % 5")).toThrow(/not all arguments converted/);
        expect(evaluateExpr("'abc' % {'a': 1}")).toBe("abc");
        expect(evaluateExpr("'%(a)s' % {'a': 1}")).toBe("1");
        expect(evaluateExpr("'%s' % (1,)")).toBe("1");
        expect(evaluateExpr("'100%%' % ()")).toBe("100%");
    });

    test("mismatched '+' raises (Python TypeError)", () => {
        expect(() => evaluateExpr("'a' + 1")).toThrow();
        expect(() => evaluateExpr("1 + 'a'")).toThrow();
        expect(evaluateExpr("'a' + 'b'")).toBe("ab");
        expect(evaluateExpr("1 + 2")).toBe(3);
        expect(evaluateExpr("True + 1")).toBe(2);
        expect(evaluateExpr("[1] + [2]")).toEqual([1, 2]);
    });

    test("dict deep equality (Python {'a': 1} == {'a': 1})", () => {
        expect(evaluateExpr("{'a': 1} == {'a': 1}")).toBe(true);
        expect(evaluateExpr("{'a': 1} == {'a': 2}")).toBe(false);
        expect(evaluateExpr("{'a': 1, 'b': 2} == {'b': 2, 'a': 1}")).toBe(true);
        expect(evaluateExpr("{'a': 1} == {'a': 1, 'b': 2}")).toBe(false);
    });

    test("set deep equality", () => {
        expect(evaluateExpr("set([1, 2, 3]) == set([3, 2, 1])")).toBe(true);
        expect(evaluateExpr("set([1, 2]) == set([1, 2, 3])")).toBe(false);
    });

    test("dict with an 'isEqual' data key does not throw", () => {
        expect(evaluateExpr("d == d", { d: { isEqual: 5, a: 1 } })).toBe(true);
    });

    test("'in' uses deep equality (Python [1, 2] in [[1, 2]])", () => {
        expect(evaluateExpr("[1, 2] in [[1, 2]]")).toBe(true);
        expect(evaluateExpr("[1, 3] in [[1, 2]]")).toBe(false);
        expect(evaluateExpr("{'a': 1} in [{'a': 1}]")).toBe(true);
    });

    test("str() of containers, dates and floats", () => {
        expect(evaluateExpr("str([1, 2])")).toBe("[1, 2]");
        expect(evaluateExpr("str([1, 'a'])")).toBe("[1, 'a']");
        expect(evaluateExpr("str({'a': 1})")).toBe("{'a': 1}");
        expect(evaluateExpr("str('a')")).toBe("a");
        expect(evaluateExpr("str(3.5)")).toBe("3.5");
        expect(evaluateExpr("str(datetime.date(2020, 1, 31))")).toBe("2020-01-31");
        expect(evaluateExpr("str(datetime.datetime(2020, 1, 31, 5, 6, 7))")).toBe(
            "2020-01-31 05:06:07",
        );
        expect(evaluateExpr("str(datetime.timedelta(days=1))")).toBe("1 day, 0:00:00");
    });

    test("strftime handles '%%' literal percent", () => {
        expect(evaluateExpr("time.strftime('100%%')")).toBe("100%");
    });

    test("'**' is right-associative (Python 2**3**2 == 512)", () => {
        expect(evaluateExpr("2 ** 3 ** 2")).toBe(512);
        expect(evaluateExpr("2 ** 2 ** 3")).toBe(256);
        expect(evaluateExpr("(2 ** 3) ** 2")).toBe(64);
        expect(evaluateExpr("2 ** 3")).toBe(8);
    });

    test("'**' raises on zero to a negative power (ZeroDivisionError, not Infinity)", () => {
        expect(() => evaluateExpr("0 ** -1")).toThrow(/ZeroDivisionError/);
        expect(() => evaluateExpr("0 ** -2")).toThrow(/ZeroDivisionError/);
        expect(() => evaluateExpr("False ** -1")).toThrow(/ZeroDivisionError/);
        expect(evaluateExpr("0 ** 0")).toBe(1);
        expect(evaluateExpr("0 ** 2")).toBe(0);
    });

    test("'**' raises on a negative base with a fractional exponent (complex, not NaN)", () => {
        expect(() => evaluateExpr("(-8) ** 0.5")).toThrow(/fractional power/);
        expect(evaluateExpr("(-2) ** 3")).toBe(-8);
        expect(evaluateExpr("(-2) ** 2")).toBe(4);
    });
});

describe("python numeric semantics", () => {
    test("division by False raises ZeroDivisionError (bool is an int)", () => {
        expect(() => evaluateExpr("1 / False")).toThrow(/ZeroDivision/);
        expect(() => evaluateExpr("5 % False")).toThrow(/ZeroDivision/);
        expect(() => evaluateExpr("5 // False")).toThrow(/ZeroDivision/);
        expect(evaluateExpr("5 / True")).toBe(5);
    });

    test("non-numeric operands raise instead of yielding NaN", () => {
        expect(() => evaluateExpr('"a" / 2')).toThrow(/unsupported operand/);
        expect(() => evaluateExpr('"a" - 2')).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("{} * {}")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("-d", { d: {} })).toThrow(/bad operand type/);
        expect(() => evaluateExpr("+d", { d: {} })).toThrow(/bad operand type/);
    });

    test("timedelta division", () => {
        expect(evaluateExpr("str(datetime.timedelta(days=1) / 2)")).toBe("12:00:00");
        expect(evaluateExpr("str(datetime.timedelta(days=1) // 2)")).toBe("12:00:00");
        expect(
            evaluateExpr("datetime.timedelta(days=1) / datetime.timedelta(hours=8)"),
        ).toBe(3);
        expect(
            evaluateExpr("datetime.timedelta(days=2) // datetime.timedelta(days=1)"),
        ).toBe(2);
        expect(
            evaluateExpr("datetime.timedelta(hours=25) // datetime.timedelta(days=1)"),
        ).toBe(1);
        expect(
            evaluateExpr(
                "str(datetime.timedelta(hours=25) % datetime.timedelta(days=1))",
            ),
        ).toBe("1:00:00");
        expect(() =>
            evaluateExpr("datetime.timedelta(days=1) / datetime.timedelta()"),
        ).toThrow(/ZeroDivision/);
    });

    test("round supports the ndigits keyword", () => {
        expect(evaluateExpr("round(2.567, ndigits=2)")).toBe(2.57);
        expect(evaluateExpr("round(2.567, 2)")).toBe(2.57);
        expect(evaluateExpr("round(2.567)")).toBe(3);
    });
});

describe("duck-typing guards", () => {
    test("truthiness of a plain dict carrying method-named keys", () => {
        expect(evaluateExpr("bool(d)", { d: { isTrue: 1 } })).toBe(true);
        expect(evaluateExpr("not d", { d: { isTrue: 1 } })).toBe(false);
        expect(evaluateExpr("bool(d)", { d: {} })).toBe(false);
        expect(() => evaluateExpr("-d", { d: { negate: 1 } })).toThrow(/bad operand/);
        expect(evaluateExpr("abs(-3.5)")).toBe(3.5);
        expect(() =>
            evaluateExpr("abs(d)", { d: { negate: 1, total_seconds: 2 } }),
        ).toThrow(/bad operand/);
    });

    test("a literal '__proto__' dict key is a plain entry", () => {
        expect(evaluateExpr("{'__proto__': 5}.get('__proto__')")).toBe(5);
        expect(evaluateExpr("len({'__proto__': 5})")).toBe(1);
    });
});

describe("string methods", () => {
    test("strip", () => {
        expect(evaluateExpr("'  ab  '.strip()")).toBe("ab");
        expect(evaluateExpr("'xxabxx'.strip('x')")).toBe("ab");
        expect(evaluateExpr("'abc'.strip('cb')")).toBe("a");
        expect(() => evaluateExpr("'a'.strip(5)")).toThrow();
    });

    test("startswith/endswith", () => {
        expect(evaluateExpr("'abc'.startswith('ab')")).toBe(true);
        expect(evaluateExpr("'abc'.startswith('b')")).toBe(false);
        expect(evaluateExpr("'abc'.startswith('b', 1)")).toBe(true);
        expect(evaluateExpr("'abc'.startswith(('x', 'a'))")).toBe(true);
        expect(evaluateExpr("'abc'.endswith('bc')")).toBe(true);
        expect(evaluateExpr("'abc'.endswith(('c', 'd'))")).toBe(true);
        expect(evaluateExpr("'abc'.endswith('b')")).toBe(false);
        expect(() => evaluateExpr("'abc'.startswith(5)")).toThrow();
    });

    test("replace", () => {
        expect(evaluateExpr("'a-b-a'.replace('a', 'z')")).toBe("z-b-z");
        expect(evaluateExpr("'aaa'.replace('a', 'b', 2)")).toBe("bba");
        expect(evaluateExpr("'abc'.replace('', '-')")).toBe("-a-b-c-");
        expect(evaluateExpr("'abc'.replace('', '-', 2)")).toBe("-a-bc");
    });

    test("split", () => {
        expect(evaluateExpr("'a b  c'.split()")).toEqual(["a", "b", "c"]);
        expect(evaluateExpr("' a  b '.split()")).toEqual(["a", "b"]);
        expect(evaluateExpr("'a,b,,c'.split(',')")).toEqual(["a", "b", "", "c"]);
        expect(evaluateExpr("'a,b,c'.split(',', 1)")).toEqual(["a", "b,c"]);
        expect(() => evaluateExpr("'abc'.split('')")).toThrow(/empty separator/);
    });

    test("join", () => {
        expect(evaluateExpr("', '.join(['a', 'b'])")).toBe("a, b");
        expect(evaluateExpr("'-'.join('abc')")).toBe("a-b-c");
        expect(() => evaluateExpr("','.join([1, 2])")).toThrow(/expected str/);
    });

    test("format", () => {
        expect(evaluateExpr("'{} and {}'.format(1, 'a')")).toBe("1 and a");
        expect(evaluateExpr("'{1}{0}'.format('a', 'b')")).toBe("ba");
        expect(evaluateExpr("'{x}'.format(x=5)")).toBe("5");
        expect(evaluateExpr("'{{}}{}'.format(3)")).toBe("{}3");
        expect(() => evaluateExpr("'{}{}'.format(1)")).toThrow(/out of range/);
        expect(() => evaluateExpr("'{y}'.format(x=5)")).toThrow(/KeyError/);
        expect(() => evaluateExpr("'{x:>8}'.format(x=3)")).toThrow(/unsupported/);
    });

    test("title/capitalize", () => {
        expect(evaluateExpr("'hello world-foo 2x'.title()")).toBe("Hello World-Foo 2X");
        expect(evaluateExpr('"it\'s a test 2b or not".title()')).toBe(
            "It'S A Test 2B Or Not",
        );
        expect(evaluateExpr("'hELLo'.capitalize()")).toBe("Hello");
        expect(evaluateExpr("''.capitalize()")).toBe("");
    });
});

describe("date/datetime/time cross-type operations", () => {
    test("cross-kind ordering raises (Python TypeError)", () => {
        expect(() =>
            evaluateExpr("datetime.date(2020,1,1) < datetime.datetime(1990,1,1)"),
        ).toThrow(/not supported between/);
        expect(() =>
            evaluateExpr("datetime.datetime(2020,1,1) > datetime.date(2020,1,2)"),
        ).toThrow(/not supported between/);
        expect(() =>
            evaluateExpr("datetime.date(2020,1,1) <= datetime.time(1,0)"),
        ).toThrow(/not supported between/);
        expect(evaluateExpr("datetime.date(2020,1,1) < datetime.date(2020,1,2)")).toBe(
            true,
        );
        expect(
            evaluateExpr(
                "datetime.datetime(2020,1,1,1) < datetime.datetime(2020,1,1,2)",
            ),
        ).toBe(true);
        expect(evaluateExpr("datetime.time(1,0) < datetime.time(2,0)")).toBe(true);
    });

    test("cross-kind equality is False, not an error", () => {
        expect(evaluateExpr("datetime.date(2020,1,1) == datetime.time(1,0)")).toBe(
            false,
        );
        expect(
            evaluateExpr("datetime.date(2020,1,1) == datetime.datetime(2020,1,1)"),
        ).toBe(false);
        expect(evaluateExpr("datetime.time(1,0) == datetime.time(1,0)")).toBe(true);
        expect(evaluateExpr("datetime.time(1,0) == datetime.time(2,0)")).toBe(false);
    });

    test("time arithmetic raises (Python TypeError)", () => {
        expect(() =>
            evaluateExpr("datetime.date(2020,1,1) - datetime.time(1,0,0)"),
        ).toThrow();
        expect(() =>
            evaluateExpr("datetime.time(1,0) - datetime.time(0,30)"),
        ).toThrow();
        expect(() =>
            evaluateExpr("datetime.time(1,0) + datetime.timedelta(days=1)"),
        ).toThrow();
        expect(
            evaluateExpr("(datetime.date(2020,1,2) - datetime.date(2020,1,1)).days"),
        ).toBe(1);
    });
});

describe("dict .get fallback", () => {
    test(".get works on generic objects but not on lists", () => {
        expect(evaluateExpr("d.get('a')", { d: { a: 1 } })).toBe(1);
        expect(evaluateExpr("d.get('b', 5)", { d: { a: 1 } })).toBe(5);
        expect(() => evaluateExpr("[1, 2].get(0)")).toThrow();
    });
});

describe("bitwise/shift arbitrary precision", () => {
    test("shifts and masks beyond 32 bits match Python, not JS 32-bit ops", () => {
        expect(evaluateExpr("1 << 40")).toBe(1099511627776);
        expect(evaluateExpr("4294967296 | 1")).toBe(4294967297);
        expect(evaluateExpr("4294967296 & 4294967296")).toBe(4294967296);
        expect(evaluateExpr("(1 << 20) >> 10")).toBe(1024);
    });

    test("a result beyond the safe integer range raises", () => {
        expect(() => evaluateExpr("1 << 60")).toThrow(/safe integer range/);
    });

    test("a negative shift count raises", () => {
        expect(() => evaluateExpr("1 << -1")).toThrow(/negative shift count/);
    });
});

describe("timedelta multiplication guards", () => {
    test("timedelta * timedelta raises instead of producing garbage", () => {
        expect(() =>
            evaluateExpr("datetime.timedelta(days=1) * datetime.timedelta(days=1)"),
        ).toThrow(/unsupported operand type/);
    });

    test("timedelta * non-number raises", () => {
        expect(() => evaluateExpr('datetime.timedelta(days=1) * "x"')).toThrow(
            /unsupported operand type/,
        );
    });
});

describe("max/min share the comparison kernel", () => {
    test("max/min over lists compare lexicographically like Python", () => {
        expect(evaluateExpr("max([[2], [10]])")).toEqual([10]);
        expect(evaluateExpr("min([[2], [10]])")).toEqual([2]);
        expect(evaluateExpr("max([[1, 2], [1, 10]])")).toEqual([1, 10]);
    });
});

describe("repr string escaping", () => {
    test("str() of a list escapes quotes into parseable repr", () => {
        expect(evaluateExpr(`str(["it's"])`)).toBe(`["it's"]`);
        expect(evaluateExpr(`'%r' % "a'b"`)).toBe(`"a'b"`);
        expect(evaluateExpr(`'%r' % 'plain'`)).toBe(`'plain'`);
    });
});

describe("CPython-alignment regressions", () => {
    test("sequence repetition by a non-int raises (no silent truncation)", () => {
        expect(() => evaluateExpr("'x' * 2.5")).toThrow(/multiply sequence/);
        expect(() => evaluateExpr("[1] * 1.9")).toThrow(/multiply sequence/);
        expect(evaluateExpr("'x' * 3")).toBe("xxx");
        expect(evaluateExpr("[1, 2] * 2")).toEqual([1, 2, 1, 2]);
        expect(evaluateExpr("'x' * True")).toBe("x");
    });

    test("printf sign/space/alt flags and non-number guard", () => {
        expect(evaluateExpr("'%+d' % 5")).toBe("+5");
        expect(evaluateExpr("'% d' % 5")).toBe(" 5");
        expect(evaluateExpr("'%#x' % 255")).toBe("0xff");
        expect(evaluateExpr("'%#o' % 8")).toBe("0o10");
        expect(() => evaluateExpr("'%d' % 'x'")).toThrow(/a number is required/);
        expect(evaluateExpr("'%d' % 5")).toBe("5");
        expect(evaluateExpr("'%05d' % -3")).toBe("-0003");
    });

    test("str.format cannot mix automatic and manual field numbering", () => {
        expect(() => evaluateExpr("'{}{0}'.format('a')")).toThrow(/cannot switch/);
        expect(() => evaluateExpr("'{0}{}'.format('a', 'b')")).toThrow(/cannot switch/);
        expect(evaluateExpr("'{} {}'.format('a', 'b')")).toBe("a b");
        expect(evaluateExpr("'{0} {1} {0}'.format('a', 'b')")).toBe("a b a");
    });

    test("str.replace with a non-int count raises (no over-replacement)", () => {
        expect(() => evaluateExpr("'aaa'.replace('a', 'b', 2.5)")).toThrow(
            /count must be an integer/,
        );
        expect(evaluateExpr("'aaa'.replace('a', 'b', 2)")).toBe("bba");
        expect(evaluateExpr("'aaa'.replace('a', 'b')")).toBe("bbb");
    });

    test("float() parses inf/nan like Infinity", () => {
        expect(evaluateExpr("float('inf')")).toBe(Infinity);
        expect(evaluateExpr("float('-inf')")).toBe(-Infinity);
        expect(evaluateExpr("float('Infinity')")).toBe(Infinity);
        expect(Number.isNaN(evaluateExpr("float('nan')"))).toBe(true);
        expect(evaluateExpr("float('3.5')")).toBe(3.5);
    });

    test("inf and nan are spelled the Python way, everywhere", () => {
        expect(evaluateExpr("str(float('inf'))")).toBe("inf");
        expect(evaluateExpr("str(float('-inf'))")).toBe("-inf");
        expect(evaluateExpr("str(float('nan'))")).toBe("nan");
        expect(evaluateExpr("repr(float('inf'))")).toBe("inf");
        expect(evaluateExpr("'%s' % float('inf')")).toBe("inf");
        expect(evaluateExpr("'%f' % float('inf')")).toBe("inf");
        expect(evaluateExpr("'%e' % float('nan')")).toBe("nan");
        expect(evaluateExpr("'%+f' % float('inf')")).toBe("+inf");
        expect(evaluateExpr("'%10.2f' % float('inf')")).toBe("       inf");
        expect(evaluateExpr("'%F' % float('inf')")).toBe("INF");
        expect(evaluateExpr("'%E' % float('inf')")).toBe("INF");
        expect(evaluateExpr("'%G' % float('nan')")).toBe("NAN");
        expect(evaluateExpr("'%F' % 2.5")).toBe("2.500000");
    });

    test("the integer conversions refuse inf and nan, by CPython's two names", () => {
        expect(() => evaluateExpr("'%d' % float('inf')")).toThrow(
            /cannot convert float infinity to integer/,
        );
        expect(() => evaluateExpr("'%d' % float('nan')")).toThrow(
            /cannot convert float NaN to integer/,
        );
    });

    test("%c takes an int or a one-character string", () => {
        expect(evaluateExpr("'%c' % 65")).toBe("A");
        expect(evaluateExpr("'%c' % 'A'")).toBe("A");
        expect(evaluateExpr("'%c' % True")).toBe("\u0001");
        expect(evaluateExpr("'%c' % 128512")).toBe("\u{1F600}");
        expect(evaluateExpr("'%5c' % 65")).toBe("    A");
        expect(evaluateExpr("'%-5c' % 65")).toBe("A    ");
        expect(() => evaluateExpr("'%c' % 'AB'")).toThrow(/a string of length 2/);
        expect(() => evaluateExpr("'%c' % 1.5")).toThrow(/not float/);
        expect(() => evaluateExpr("'%c' % 1114112")).toThrow(/range\(0x110000\)/);
    });

    test("small floats use Python's exponent form and padding", () => {
        expect(evaluateExpr("repr(0.0001)")).toBe("0.0001");
        expect(evaluateExpr("repr(0.00001)")).toBe("1e-05");
        expect(evaluateExpr("repr(1e-7)")).toBe("1e-07");
        expect(evaluateExpr("repr(1.5e-5)")).toBe("1.5e-05");
        expect(evaluateExpr("'%s' % 0.000012345")).toBe("1.2345e-05");
        expect(evaluateExpr("str(0.001)")).toBe("0.001");
        expect(evaluateExpr("str(1.5)")).toBe("1.5");
        expect(evaluateExpr("str(0)")).toBe("0");
    });
});

describe("builtin fidelity", () => {
    test("bool/len/abs reject extra positional arguments (CPython arity)", () => {
        expect(() => evaluateExpr("bool(1, 2)")).toThrow(
            /bool expected at most 1 argument/,
        );
        expect(() => evaluateExpr("len([1], 2)")).toThrow(/len\(\) takes exactly one/);
        expect(() => evaluateExpr("abs(1, 2)")).toThrow(/abs\(\) takes exactly one/);
        expect(evaluateExpr("bool(1)")).toBe(true);
        expect(evaluateExpr("len([1, 2])")).toBe(2);
        expect(evaluateExpr("abs(-3)")).toBe(3);
    });

    test("bool(relativedelta()) matches dateutil __bool__", () => {
        expect(evaluateExpr("bool(relativedelta())")).toBe(false);
        expect(evaluateExpr("bool(relativedelta(days=0))")).toBe(false);
        expect(evaluateExpr("bool(relativedelta(days=1))")).toBe(true);
        expect(evaluateExpr("bool(relativedelta(year=2020))")).toBe(true);
        expect(evaluateBooleanExpr("not relativedelta(days=0)")).toBe(true);
    });

    test("calling a non-whitelisted function raises an EvaluationError", () => {
        expect(() => evaluateExpr("foo()", { foo: () => 1 })).toThrow(
            /Invalid Function Call/,
        );
    });
});

describe("set algebra operators", () => {
    test("| & - ^ operate on sets", () => {
        expect(evaluateExpr("set([1, 2]) | set([2, 3])")).toEqual(new Set([1, 2, 3]));
        expect(evaluateExpr("set([1, 2]) & set([2, 3])")).toEqual(new Set([2]));
        expect(evaluateExpr("set([1, 2]) - set([2, 3])")).toEqual(new Set([1]));
        expect(evaluateExpr("set([1, 2]) ^ set([2, 3])")).toEqual(new Set([1, 3]));
    });

    test("mixing a set with a non-set still raises", () => {
        expect(() => evaluateExpr("set([1]) | 1")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("1 | set([1])")).toThrow(/unsupported operand/);
        expect(() => evaluateExpr("set([1]) << set([1])")).toThrow(
            /unsupported operand/,
        );
    });

    test("integer bitwise operators are untouched", () => {
        expect(evaluateExpr("5 & 3")).toBe(1);
        expect(evaluateExpr("5 | 3")).toBe(7);
        expect(evaluateExpr("5 ^ 3")).toBe(6);
        expect(evaluateExpr("1 << 10")).toBe(1024);
    });
});

describe("ordering stays total across types (see pytypeIndex)", () => {
    test("an unset field compares against a date string without raising", () => {
        expect(
            evaluateExpr("datetime > '2017-02-27 12:51:35'", { datetime: false }),
        ).toBe(false);
        expect(
            evaluateExpr("datetime < '2017-02-27 12:51:35'", { datetime: false }),
        ).toBe(true);
        expect(
            evaluateExpr("birthday > today", { birthday: false, today: "2020-01-01" }),
        ).toBe(false);
    });
});

describe("attribute access raises like safe_eval, instead of yielding undefined", () => {
    test("absent member of a dict, str or set", () => {
        expect(() => evaluateExpr("{'a': 1}.b")).toThrow(
            /AttributeError: 'dict' object has no attribute 'b'/,
        );
        expect(() => evaluateExpr("'abc'.foo")).toThrow(
            /AttributeError: 'str' object has no attribute 'foo'/,
        );
        expect(() => evaluateExpr("set([1]).foo")).toThrow(
            /AttributeError: 'set' object has no attribute 'foo'/,
        );
    });

    test("the comparison that used to answer false", () => {
        expect(() => evaluateExpr("{'a': 1}.b == None")).toThrow(/AttributeError/);
        expect(() => evaluateExpr("1 if 'abc'.nope else 2")).toThrow(/AttributeError/);
    });

    test("a dict literal no longer loses a key silently", () => {
        expect(() => evaluateExpr("{'x': 'abc'.nope}")).toThrow(/AttributeError/);
    });

    test("Object.prototype members are not members of a py value", () => {
        expect(() => evaluateExpr("{'a': 1}.toString")).toThrow(
            /AttributeError: 'dict' object has no attribute 'toString'/,
        );
        expect(() => evaluateExpr("'abc'.constructor")).toThrow(/AttributeError/);
    });

    test("None has no attributes", () => {
        expect(() => evaluateExpr("None.foo")).toThrow(
            /AttributeError: 'NoneType' object has no attribute 'foo'/,
        );
    });

    test("the members that do exist still resolve", () => {
        expect(evaluateExpr("{'a': 1}.get('a')")).toBe(1);
        expect(evaluateExpr("{'a': 1}.get('b', 9)")).toBe(9);
        expect(evaluateExpr("'aBc'.lower()")).toBe("abc");
        expect(evaluateExpr("set([1, 2]).union([3])")).toEqual(new Set([1, 2, 3]));
    });

    test("absent member of a temporal, a number or a list", () => {
        expect(() => evaluateExpr("datetime.date(2024, 1, 1).nope")).toThrow(
            /AttributeError: 'date' object has no attribute 'nope'/,
        );
        expect(() => evaluateExpr("datetime.datetime(2024, 1, 1).nope")).toThrow(
            /AttributeError: 'datetime' object has no attribute 'nope'/,
        );
        expect(() => evaluateExpr("datetime.timedelta(days=1).nope")).toThrow(
            /AttributeError: 'timedelta' object has no attribute 'nope'/,
        );
        expect(() => evaluateExpr("[1, 2].nope")).toThrow(
            /AttributeError: 'list' object has no attribute 'nope'/,
        );
        expect(() => evaluateExpr("(1).nope")).toThrow(
            /AttributeError: 'int' object has no attribute 'nope'/,
        );
    });

    test("a call to an absent method names the attribute, not V8's receiver", () => {
        expect(() => evaluateExpr("datetime.date(2024, 1, 1).isoformat()")).toThrow(
            /AttributeError: 'date' object has no attribute 'isoformat'/,
        );
        expect(() => evaluateExpr("datetime.date(2024, 1, 1).timetuple()")).toThrow(
            /AttributeError: 'date' object has no attribute 'timetuple'/,
        );
    });

    test("the temporal members that do exist still resolve", () => {
        expect(evaluateExpr("datetime.date(2024, 1, 1).year")).toBe(2024);
        expect(evaluateExpr("datetime.datetime(2024, 1, 1, 5, 0, 0).hour")).toBe(5);
        expect(evaluateExpr("datetime.date(2024, 1, 1).strftime('%Y')")).toBe("2024");
        expect(evaluateExpr("datetime.timedelta(days=1).total_seconds()")).toBe(86400);
    });

    test("a host object still reads absent keys as undefined", () => {
        expect(evaluateExpr("parent.absent", { parent: { a: 1 } })).toBe(undefined);
    });
});
