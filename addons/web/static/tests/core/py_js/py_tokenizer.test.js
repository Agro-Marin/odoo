// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { tokenize } from "@web/core/py_js/py";

describe.current.tags("headless");

test("can tokenize simple expressions with spaces", () => {
    expect(tokenize("1")).toEqual([{ type: 0, value: 1 }]);
    expect(tokenize(" 1")).toEqual([{ type: 0, value: 1 }]);
    expect(tokenize(" 1 ")).toEqual([{ type: 0, value: 1 }]);
});

test("can tokenize numbers", () => {
    expect(tokenize("1")).toEqual([{ type: 0, value: 1 }]);
    expect(tokenize("13")).toEqual([{ type: 0, value: 13 }]);
    expect(tokenize("-1")).toEqual([
        { type: 2, value: "-" },
        { type: 0, value: 1 },
    ]);

    expect(tokenize("1e2")).toEqual([{ type: 0, value: 100 }]);
    expect(tokenize("13E+02")).toEqual([{ type: 0, value: 1300 }]);
    expect(tokenize("15E-2")).toEqual([{ type: 0, value: 0.15 }]);
    expect(tokenize("-30e+002")).toEqual([
        { type: 2, value: "-" },
        { type: 0, value: 3000 },
    ]);
});

test("can tokenize floats", () => {
    expect(tokenize("12.0")).toEqual([{ type: 0, value: 12 }]);
    expect(tokenize("1.2")).toEqual([{ type: 0, value: 1.2 }]);
    expect(tokenize(".42")).toEqual([{ type: 0, value: 0.42 }]);
    expect(tokenize("12.")).toEqual([{ type: 0, value: 12 }]);
    expect(tokenize("-1.23")).toEqual([
        { type: 2, value: "-" },
        { type: 0, value: 1.23 },
    ]);

    expect(tokenize("1234e-3")).toEqual([{ type: 0, value: 1.234 }]);
    expect(tokenize("1.23E-03")).toEqual([{ type: 0, value: 0.00123 }]);
    expect(tokenize(".23e-3")).toEqual([{ type: 0, value: 0.00023 }]);
    expect(tokenize("23.e-03")).toEqual([{ type: 0, value: 0.023 }]);

    expect(tokenize("12.1E2")).toEqual([{ type: 0, value: 1210 }]);
    expect(tokenize("1.23e+03")).toEqual([{ type: 0, value: 1230 }]);
    expect(tokenize(".23e2")).toEqual([{ type: 0, value: 23 }]);
    expect(tokenize("15.E+02")).toEqual([{ type: 0, value: 1500 }]);

    expect(tokenize("-23E02")).toEqual([
        { type: 2, value: "-" },
        { type: 0, value: 2300 },
    ]);
});

test("can tokenize base-prefixed integer literals", () => {
    expect(tokenize("0x10")).toEqual([{ type: 0, value: 16 }]);
    expect(tokenize("0X1F")).toEqual([{ type: 0, value: 31 }]);
    expect(tokenize("0o17")).toEqual([{ type: 0, value: 15 }]);
    expect(tokenize("0O10")).toEqual([{ type: 0, value: 8 }]);
    expect(tokenize("0b101")).toEqual([{ type: 0, value: 5 }]);
    expect(tokenize("0B1111")).toEqual([{ type: 0, value: 15 }]);
    expect(tokenize("0x10 + 0b10")).toEqual([
        { type: 0, value: 16 },
        { type: 2, value: "+" },
        { type: 0, value: 2 },
    ]);
});

test("can tokenize numeric literals with underscore digit separators (PEP 515)", () => {
    expect(tokenize("1_000")).toEqual([{ type: 0, value: 1000 }]);
    expect(tokenize("1_000_000")).toEqual([{ type: 0, value: 1000000 }]);
    expect(tokenize("0xDE_AD")).toEqual([{ type: 0, value: 57005 }]);
    expect(tokenize("1_0.5_0")).toEqual([{ type: 0, value: 10.5 }]);
    expect(tokenize("10L")).toEqual([{ type: 0, value: 10 }]);
    expect(tokenize("1__0")).toEqual([
        { type: 0, value: 1 },
        { type: 3, value: "__0" },
    ]);
});

test("can tokenize strings", () => {
    expect(tokenize('"foo"')).toEqual([{ type: 1, value: "foo" }]);
});

test("decodes escape sequences with Python 3 semantics", () => {
    expect(tokenize(String.raw`"caf\u00e9"`)).toEqual([{ type: 1, value: "café" }]);
    expect(tokenize(String.raw`'caf\u00e9'`)).toEqual([{ type: 1, value: "café" }]);
    expect(tokenize(String.raw`u"caf\u00e9"`)).toEqual([{ type: 1, value: "café" }]);
    expect(tokenize(String.raw`"\U0001F600"`)).toEqual([{ type: 1, value: "😀" }]);
    expect(tokenize(String.raw`"\x41"`)).toEqual([{ type: 1, value: "A" }]);
    expect(tokenize(String.raw`"\101"`)).toEqual([{ type: 1, value: "A" }]);
    expect(tokenize(String.raw`u"\x41"`)).toEqual([{ type: 1, value: "A" }]);
    expect(tokenize(String.raw`"a\nb"`)).toEqual([{ type: 1, value: "a\nb" }]);
    expect(tokenize(String.raw`"\d"`)).toEqual([{ type: 1, value: "\\d" }]);
    expect(() => tokenize(String.raw`"\N{BULLET}"`)).toThrow(/not implemented/);
    expect(() => tokenize(String.raw`"\u00"`)).toThrow(/truncated/);
    expect(() => tokenize(String.raw`"\U0001"`)).toThrow(/truncated/);
    expect(() => tokenize(String.raw`"\x4"`)).toThrow(/truncated/);
});

test("normalizes the legacy <> operator to !=", () => {
    expect(tokenize("a <> b")).toEqual([
        { type: 3, value: "a" },
        { type: 2, value: "!=" },
        { type: 3, value: "b" },
    ]);
});

test("can tokenize bare names", () => {
    expect(tokenize("foo")).toEqual([{ type: 3, value: "foo" }]);
});

test("can tokenize misc operators", () => {
    expect(tokenize("in")).toEqual([{ type: 2, value: "in" }]);
    expect(tokenize("not in")).toEqual([{ type: 2, value: "not in" }]);
    expect(tokenize("3 ** 2")[1]).toEqual({ type: 2, value: "**" });
});

test("can tokenize constants", () => {
    expect(tokenize("None")).toEqual([{ type: 4, value: "None" }]);
    expect(tokenize("True")).toEqual([{ type: 4, value: "True" }]);
    expect(tokenize("False")).toEqual([{ type: 4, value: "False" }]);
});

test("can tokenize parenthesis", () => {
    expect(tokenize("()")).toEqual([
        { type: 2, value: "(" },
        { type: 2, value: ")" },
    ]);
});

test("can tokenize function with kwargs", () => {
    expect(tokenize('foo(bar=3, qux="4")')).toEqual([
        { type: 3, value: "foo" },
        { type: 2, value: "(" },
        { type: 3, value: "bar" },
        { type: 2, value: "=" },
        { type: 0, value: 3 },
        { type: 2, value: "," },
        { type: 3, value: "qux" },
        { type: 2, value: "=" },
        { type: 1, value: "4" },
        { type: 2, value: ")" },
    ]);
});

test("can tokenize if statement", () => {
    expect(tokenize("1 if True else 2")).toEqual([
        { type: 0, value: 1 },
        { type: 2, value: "if" },
        { type: 4, value: "True" },
        { type: 2, value: "else" },
        { type: 0, value: 2 },
    ]);
});

test("sanity check: throw some errors", () => {
    expect(() => tokenize("'asdf")).toThrow();
});
