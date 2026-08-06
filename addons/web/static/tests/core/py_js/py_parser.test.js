// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { clearASTCache, parseExpr } from "@web/core/py_js/py";

describe.current.tags("headless");

test("can parse basic elements", () => {
    expect(parseExpr("1")).toEqual({ type: 0, value: 1 });
    expect(parseExpr('"foo"')).toEqual({ type: 1, value: "foo" });
    expect(parseExpr("foo")).toEqual({ type: 5, value: "foo" });
    expect(parseExpr("True")).toEqual({ type: 2, value: true });
    expect(parseExpr("False")).toEqual({ type: 2, value: false });
    expect(parseExpr("None")).toEqual({ type: 3 });
});

test("cannot parse empty string", () => {
    expect(() => parseExpr("")).toThrow(/Error: Missing token/);
});

test("can parse unary operator -", () => {
    expect(parseExpr("-1")).toEqual({
        type: 6,
        op: "-",
        right: { type: 0, value: 1 },
    });
    expect(parseExpr("-foo")).toEqual({
        type: 6,
        op: "-",
        right: { type: 5, value: "foo" },
    });
    expect(parseExpr("not True")).toEqual({
        type: 6,
        op: "not",
        right: { type: 2, value: true },
    });
});

test("can parse parenthesis", () => {
    expect(parseExpr("(1 + 2)")).toEqual({
        type: 7,
        op: "+",
        left: { type: 0, value: 1 },
        right: { type: 0, value: 2 },
    });
});

test("can parse binary operators", () => {
    expect(parseExpr("1 < 2")).toEqual({
        type: 7,
        op: "<",
        left: { type: 0, value: 1 },
        right: { type: 0, value: 2 },
    });
    expect(parseExpr('a + "foo"')).toEqual({
        type: 7,
        op: "+",
        left: { type: 5, value: "a" },
        right: { type: 1, value: "foo" },
    });
});

test("can parse boolean operators", () => {
    expect(parseExpr('True and "foo"')).toEqual({
        type: 14,
        op: "and",
        left: { type: 2, value: true },
        right: { type: 1, value: "foo" },
    });
    expect(parseExpr('True or "foo"')).toEqual({
        type: 14,
        op: "or",
        left: { type: 2, value: true },
        right: { type: 1, value: "foo" },
    });
});

test("expression with == and or", () => {
    expect(parseExpr("False == True and False")).toEqual({
        type: 14,
        op: "and",
        left: {
            type: 7,
            op: "==",
            left: { type: 2, value: false },
            right: { type: 2, value: true },
        },
        right: { type: 2, value: false },
    });
});

test("expression with + and ==", () => {
    expect(parseExpr("1 + 2 == 3")).toEqual({
        type: 7,
        op: "==",
        left: {
            type: 7,
            op: "+",
            left: { type: 0, value: 1 },
            right: { type: 0, value: 2 },
        },
        right: { type: 0, value: 3 },
    });
});

test("can parse chained comparisons", () => {
    // One node with N+1 operands, not `(a < b) and (b < c)`: the desugaring
    // shared the middle operand between both halves, so it was evaluated twice
    // and formatAST could not spell the expression back.
    expect(parseExpr("1 < 2 <= 3")).toEqual({
        type: 16,
        operands: [
            { type: 0, value: 1 },
            { type: 0, value: 2 },
            { type: 0, value: 3 },
        ],
        operators: ["<", "<="],
    });
    expect(parseExpr("1 < 2 <= 3 > 33")).toEqual({
        type: 16,
        operands: [
            { type: 0, value: 1 },
            { type: 0, value: 2 },
            { type: 0, value: 3 },
            { type: 0, value: 33 },
        ],
        operators: ["<", "<=", ">"],
    });
    // a single comparison stays a plain binary operator
    expect(parseExpr("1 < 2")).toEqual({
        type: 7,
        op: "<",
        left: { type: 0, value: 1 },
        right: { type: 0, value: 2 },
    });
});

test("can parse lists", () => {
    expect(parseExpr("[]")).toEqual({
        type: 4,
        value: [],
    });
    expect(parseExpr("[1]")).toEqual({
        type: 4,
        value: [{ type: 0, value: 1 }],
    });
    expect(parseExpr("[1,]")).toEqual({
        type: 4,
        value: [{ type: 0, value: 1 }],
    });
    expect(parseExpr("[1, 4]")).toEqual({
        type: 4,
        value: [
            { type: 0, value: 1 },
            { type: 0, value: 4 },
        ],
    });
    expect(() => parseExpr("[1 1]")).toThrow();
});

test("can parse lists lookup", () => {
    expect(parseExpr("[1,2][1]")).toEqual({
        type: 12,
        target: {
            type: 4,
            value: [
                { type: 0, value: 1 },
                { type: 0, value: 2 },
            ],
        },
        key: { type: 0, value: 1 },
    });
});

test("can parse tuples", () => {
    expect(parseExpr("()")).toEqual({
        type: 10,
        value: [],
    });
    expect(parseExpr("(1,)")).toEqual({
        type: 10,
        value: [{ type: 0, value: 1 }],
    });
    expect(parseExpr("(1,4)")).toEqual({
        type: 10,
        value: [
            { type: 0, value: 1 },
            { type: 0, value: 4 },
        ],
    });
    expect(() => parseExpr("(1 1)")).toThrow();
});

test("can parse dictionary", () => {
    expect(parseExpr("{}")).toEqual({
        type: 11,
        value: {},
    });
    expect(parseExpr("{'foo': 1}")).toEqual({
        type: 11,
        value: { foo: { type: 0, value: 1 } },
    });
    expect(parseExpr("{'foo': 1, 'bar': 3}")).toEqual({
        type: 11,
        value: {
            foo: { type: 0, value: 1 },
            bar: { type: 0, value: 3 },
        },
    });
    expect(parseExpr("{1: 2}")).toEqual({
        type: 11,
        value: { 1: { type: 0, value: 2 } },
    });
});

test("can parse dictionary lookup", () => {
    expect(parseExpr("{}['a']")).toEqual({
        type: 12,
        target: { type: 11, value: {} },
        key: { type: 1, value: "a" },
    });
});

test("can parse assignment", () => {
    expect(parseExpr("a=1")).toEqual({
        type: 9,
        name: { type: 5, value: "a" },
        value: { type: 0, value: 1 },
    });
});

test("can parse function calls", () => {
    expect(parseExpr("f()")).toEqual({
        type: 8,
        fn: { type: 5, value: "f" },
        args: [],
        kwargs: {},
    });
    expect(parseExpr("f() + 2")).toEqual({
        type: 7,
        op: "+",
        left: {
            type: 8,
            fn: { type: 5, value: "f" },
            args: [],
            kwargs: {},
        },
        right: { type: 0, value: 2 },
    });
    expect(parseExpr("f(1)")).toEqual({
        type: 8,
        fn: { type: 5, value: "f" },
        args: [{ type: 0, value: 1 }],
        kwargs: {},
    });
    expect(parseExpr("f(1, 2)")).toEqual({
        type: 8,
        fn: { type: 5, value: "f" },
        args: [
            { type: 0, value: 1 },
            { type: 0, value: 2 },
        ],
        kwargs: {},
    });
});

test("can parse function calls with kwargs", () => {
    expect(parseExpr("f(a = 1)")).toEqual({
        type: 8,
        fn: { type: 5, value: "f" },
        args: [],
        kwargs: { a: { type: 0, value: 1 } },
    });
    expect(parseExpr("f(3, a = 1)")).toEqual({
        type: 8,
        fn: { type: 5, value: "f" },
        args: [{ type: 0, value: 3 }],
        kwargs: { a: { type: 0, value: 1 } },
    });
});

test("can parse not a in b", () => {
    expect(parseExpr("not a in b")).toEqual({
        type: 6,
        op: "not",
        right: {
            type: 7,
            op: "in",
            left: { type: 5, value: "a" },
            right: { type: 5, value: "b" },
        },
    });
    expect(parseExpr("a.b.c")).toEqual({
        type: 15,
        obj: {
            type: 15,
            obj: { type: 5, value: "a" },
            key: "b",
        },
        key: "c",
    });
});

test("can parse if statement", () => {
    expect(parseExpr("1 if True else 2")).toEqual({
        type: 13,
        condition: { type: 2, value: true },
        ifTrue: { type: 0, value: 1 },
        ifFalse: { type: 0, value: 2 },
    });
    expect(parseExpr("1 + 1 if True else 2")).toEqual({
        type: 13,
        condition: { type: 2, value: true },
        ifTrue: {
            type: 7,
            op: "+",
            left: { type: 0, value: 1 },
            right: { type: 0, value: 1 },
        },
        ifFalse: { type: 0, value: 2 },
    });
});

test("tuple in list", () => {
    expect(parseExpr("[(1,2)]")).toEqual({
        type: 4,
        value: [
            {
                type: 10,
                value: [
                    { type: 0, value: 1 },
                    { type: 0, value: 2 },
                ],
            },
        ],
    });
});

test("cannot parse []a", () => {
    expect(() => parseExpr("[]a")).toThrow(/Error: Token\(s\) unused/);
    expect(() => parseExpr("[]a b")).toThrow(/Error: Token\(s\) unused/);
});

describe("AST cache", () => {
    test("parseExpr returns identical AST for repeated calls", () => {
        const ast1 = parseExpr("1 + 2");
        const ast2 = parseExpr("1 + 2");
        expect(ast1).toBe(ast2);
    });

    test("parseExpr returns different AST for different expressions", () => {
        const ast1 = parseExpr("1 + 2");
        const ast2 = parseExpr("3 + 4");
        expect(ast1).not.toBe(ast2);
    });

    test("clearASTCache invalidates cached ASTs", () => {
        const ast1 = parseExpr("a + b");
        clearASTCache();
        const ast2 = parseExpr("a + b");
        expect(ast1).not.toBe(ast2);
        expect(ast1).toEqual(ast2);
    });

    test("repeatedly read entry survives eviction pressure (LRU, not FIFO)", () => {
        clearASTCache();
        const hot = parseExpr("hot_key + 1");
        // Insert more distinct expressions than the cache holds (512), touching
        // the hot entry between inserts: an LRU keeps it, a FIFO evicts it.
        for (let i = 0; i < 600; i++) {
            parseExpr(`filler_${i} + 1`);
            parseExpr("hot_key + 1");
        }
        expect(parseExpr("hot_key + 1")).toBe(hot);
        clearASTCache();
    });
});

describe("hardening", () => {
    test("deeply nested input raises a ParserError instead of a RangeError", () => {
        const expr = "(".repeat(5000) + "1" + ")".repeat(5000);
        expect(() => parseExpr(expr)).toThrow(/Maximum expression depth exceeded/);
    });

    test("a literal __proto__ kwarg becomes a plain own entry, not a prototype write", () => {
        const ast = /** @type {any} */ (parseExpr("f(__proto__=1)"));
        expect(Object.hasOwn(ast.kwargs, "__proto__")).toBe(true);
    });
});
