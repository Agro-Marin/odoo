// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateBooleanExpr, evaluateExpr } from "@web/core/py_js/py";

describe.current.tags("headless");

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
        // second clause should nameerror if evaluated
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
        expect(() => evaluateExpr("obj.f(3)", { obj: { f: (n) => n + 1 } })).toThrow();
    });
});

describe("if expressions", () => {
    test("simple if expressions", () => {
        expect(evaluateExpr("1 if True else 2")).toBe(1);
        expect(evaluateExpr("1 if 3 < 2 else 'greater'")).toBe("greater");
    });

    test("only evaluate proper branch", () => {
        // will throw if evaluate wrong branch => name error
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
        expect(evaluateBooleanExpr("1 or a")).toBe(true); // do not throw (lazy value)
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

        expect(() => evaluateExpr("set([], [])")).toThrow(); // valid but not supported by py_js
        expect(() => evaluateExpr("set({ 'a' })")).toThrow(); // valid but not supported by py_js
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

        expect(() => evaluateExpr("set([]).intersection([], [])")).toThrow(); // valid but not supported by py_js
        expect(() => evaluateExpr("set([]).intersection([], [], [])")).toThrow(); // valid but not supported by py_js
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

        expect(() => evaluateExpr("set([]).difference([], [])")).toThrow(); // valid but not supported by py_js
        expect(() => evaluateExpr("set([]).difference([], [], [])")).toThrow(); // valid but not supported by py_js
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

        expect(() => evaluateExpr("set([]).union([], [])")).toThrow(); // valid but not supported by py_js
        expect(() => evaluateExpr("set([]).union([], [], [])")).toThrow(); // valid but not supported by py_js
    });
});

// Tests for audit improvements (builtins, security, operators, cache)

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
        expect(evaluateExpr("abs(-3.14)")).toBeCloseTo(3.14);
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
    test("int from boolean", () => {
        expect(evaluateExpr("int(True)")).toBe(1);
        expect(evaluateExpr("int(False)")).toBe(0);
    });
    test("int rejects non-integer strings", () => {
        expect(() => evaluateExpr('int("42abc")')).toThrow(/invalid literal/);
        expect(() => evaluateExpr('int("abc")')).toThrow(/invalid literal/);
        expect(() => evaluateExpr('int("")')).toThrow(/invalid literal/);
    });
});

describe("builtins — float", () => {
    test("float from string", () => {
        expect(evaluateExpr('float("3.14")')).toBeCloseTo(3.14);
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
});

describe("builtins — round", () => {
    test("round to integer", () => {
        expect(evaluateExpr("round(3.7)")).toBe(4);
        expect(evaluateExpr("round(3.2)")).toBe(3);
    });
    test("round with ndigits", () => {
        expect(evaluateExpr("round(3.14159, 2)")).toBeCloseTo(3.14);
        expect(evaluateExpr("round(1234.5, -2)")).toBe(1200);
    });
    test("round uses banker's rounding (half-to-even)", () => {
        // Python: round(0.5) → 0, round(1.5) → 2, round(2.5) → 2
        expect(evaluateExpr("round(0.5)")).toBe(0);
        expect(evaluateExpr("round(1.5)")).toBe(2);
        expect(evaluateExpr("round(2.5)")).toBe(2);
        expect(evaluateExpr("round(3.5)")).toBe(4);
    });
    test("round negative half-to-even", () => {
        // Python: round(-0.5) → 0, round(-1.5) → -2
        expect(evaluateExpr("round(-0.5)")).toBe(0);
        expect(evaluateExpr("round(-1.5)")).toBe(-2);
        expect(evaluateExpr("round(-2.5)")).toBe(-2);
    });
    test("round matches Python IEEE-754 behaviour for ndigits > 0", () => {
        // These depend on the actual IEEE-754 stored value, NOT the decimal literal.
        // 2.675 is stored as 2.6749... (below halfway) → rounds DOWN
        expect(evaluateExpr("round(2.675, 2)")).toBeCloseTo(2.67);
        // 0.45 is stored as 0.4500...001 (above halfway) → rounds UP
        expect(evaluateExpr("round(0.45, 1)")).toBeCloseTo(0.5);
        // 0.35 is stored as 0.3499... (below halfway) → rounds DOWN
        expect(evaluateExpr("round(0.35, 1)")).toBeCloseTo(0.3);
        // 0.25 is stored as 0.25 exactly (halfway) → banker's → 0.2 (even)
        expect(evaluateExpr("round(0.25, 1)")).toBeCloseTo(0.2);
        // 0.15 is stored as 0.1499... (below halfway) → rounds DOWN
        expect(evaluateExpr("round(0.15, 1)")).toBeCloseTo(0.1);
    });
    test("round with negative ndigits", () => {
        // Python: round(150, -2) → 200, round(250, -2) → 200
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
        // Parens are flattened by the parser and ternaries short-circuit on True,
        // so neither recurses deeply. Chained `and` builds a left-recursive AST
        // that must evaluate each left subtree first, reaching MAX_EVAL_DEPTH.
        const depth = 150;
        const expr = "True and ".repeat(depth) + "1";
        expect(() => evaluateExpr(expr)).toThrow(/depth/i);
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
    });
    test("left shift", () => {
        expect(evaluateExpr("1 << 3")).toBe(8);
    });
    test("right shift", () => {
        expect(evaluateExpr("8 >> 2")).toBe(2);
    });
});

describe("in operator — Object.hasOwn", () => {
    test("'in' checks own properties only (not prototype)", () => {
        // toString exists on Object.prototype but not as own property
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
        // positive indexing unaffected
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
        // numeric multiplication unaffected
        expect(evaluateExpr("3 * 4")).toBe(12);
    });

    test("'%' string formatting", () => {
        expect(evaluateExpr("'%s' % 5")).toBe("5");
        expect(evaluateExpr("'%s and %s' % (1, 2)")).toBe("1 and 2");
        expect(evaluateExpr("'%d apples' % 3")).toBe("3 apples");
        expect(evaluateExpr("'%s' % 'x'")).toBe("x");
        expect(evaluateExpr("'%(name)s' % {'name': 'foo'}")).toBe("foo");
        // numeric modulo unaffected
        expect(evaluateExpr("7 % 3")).toBe(1);
    });

    test("mismatched '+' raises (Python TypeError)", () => {
        expect(() => evaluateExpr("'a' + 1")).toThrow();
        expect(() => evaluateExpr("1 + 'a'")).toThrow();
        // valid additions still work
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
        // a context dict whose key happens to be "isEqual" is data, not a method
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
        // td / n → timedelta
        expect(evaluateExpr("str(datetime.timedelta(days=1) / 2)")).toBe("12:00:00");
        // td // n → timedelta (floored)
        expect(evaluateExpr("str(datetime.timedelta(days=1) // 2)")).toBe("12:00:00");
        // td / td → float ratio
        expect(
            evaluateExpr("datetime.timedelta(days=1) / datetime.timedelta(hours=8)"),
        ).toBe(3);
        // td // td → int
        expect(
            evaluateExpr("datetime.timedelta(days=2) // datetime.timedelta(days=1)"),
        ).toBe(2);
        expect(
            evaluateExpr("datetime.timedelta(hours=25) // datetime.timedelta(days=1)"),
        ).toBe(1);
        // td % td → timedelta
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
        // A data dict with an `isTrue`/`negate` KEY (not a method) must be
        // treated as a plain non-empty dict, not crash on a call attempt.
        expect(evaluateExpr("bool(d)", { d: { isTrue: 1 } })).toBe(true);
        expect(evaluateExpr("not d", { d: { isTrue: 1 } })).toBe(false);
        expect(evaluateExpr("bool(d)", { d: {} })).toBe(false);
        expect(() => evaluateExpr("-d", { d: { negate: 1 } })).toThrow(/bad operand/);
        // abs() must not call a data value: `d.negate`/`d.total_seconds` are
        // keys here, not the PyTimeDelta protocol.
        expect(evaluateExpr("abs(-3.5)")).toBe(3.5);
        expect(() =>
            evaluateExpr("abs(d)", { d: { negate: 1, total_seconds: 2 } }),
        ).not.toThrow();
    });

    test("a literal '__proto__' dict key is a plain entry", () => {
        expect(evaluateExpr("{'__proto__': 5}.get('__proto__')")).toBe(5);
        expect(evaluateExpr("len({'__proto__': 5})")).toBe(1);
    });
});
