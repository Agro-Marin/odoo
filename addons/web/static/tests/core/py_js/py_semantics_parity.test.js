// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr, parseExpr } from "@web/core/py_js/py";
import { formatAST } from "@web/core/py_js/py_utils";

describe.current.tags("headless");

describe("py_js answers only what safe_eval answers", () => {
    test("a name is looked up on BUILTINS itself, not on Object.prototype", () => {
        for (const name of [
            "__proto__",
            "constructor",
            "valueOf",
            "toString",
            "hasOwnProperty",
            "isPrototypeOf",
            "propertyIsEnumerable",
            "toLocaleString",
        ]) {
            expect(() => evaluateExpr(name)).toThrow(
                new RegExp(`'${name}' is not defined`),
            );
        }
        expect(evaluateExpr("bool(1)")).toBe(true);
        expect(typeof evaluateExpr("today")).toBe("string");
    });

    test("a missing dict key raises KeyError", () => {
        expect(() => evaluateExpr("{'a': 1}['b']")).toThrow(/KeyError: 'b'/);
        expect(() => evaluateExpr("{'a': 1}['b'] == None")).toThrow(/KeyError: 'b'/);
        expect(evaluateExpr("{'a': 1}['a']")).toBe(1);
        expect(evaluateExpr("{'a': 1}.get('b')")).toBe(null);
        expect(evaluateExpr("{'a': 1}.get('b', 7)")).toBe(7);
    });

    test("an out-of-range index raises IndexError", () => {
        expect(() => evaluateExpr("[1, 2, 3][9]")).toThrow(/IndexError/);
        expect(() => evaluateExpr("[1, 2, 3][-9]")).toThrow(/IndexError/);
        expect(() => evaluateExpr("'abc'[9]")).toThrow(/IndexError/);
        expect(() => evaluateExpr("[1, 2, 3]['x']")).toThrow(
            /indices must be integers/,
        );
        expect(evaluateExpr("[1, 2, 3][0]")).toBe(1);
        expect(evaluateExpr("[1, 2, 3][-1]")).toBe(3);
        expect(evaluateExpr("'abc'[-1]")).toBe("c");
    });

    test("surplus arguments and unknown keywords are rejected", () => {
        expect(() => evaluateExpr("'abc'.strip('a', 'b')")).toThrow(
            /at most 1 argument/,
        );
        expect(() => evaluateExpr("'abc'.strip(bogus=1)")).toThrow(
            /unexpected keyword argument 'bogus'/,
        );
        expect(() => evaluateExpr("'abc'.strip('a', chars='b')")).toThrow(
            /multiple values for argument 'chars'/,
        );
        expect(evaluateExpr("'abc'.strip('a')")).toBe("bc");
        expect(evaluateExpr("'abc'.strip(chars='a')")).toBe("bc");
        expect(evaluateExpr("'a,b'.split(',', 1)")).toEqual(["a", "b"]);
    });

    test("replace() validates count before honouring a negative one", () => {
        expect(() => evaluateExpr("'aaa'.replace('a', 'b', -1.5)")).toThrow(
            /count must be an integer/,
        );
        expect(evaluateExpr("'aaa'.replace('a', 'b', -1)")).toBe("bbb");
        expect(evaluateExpr("'aaa'.replace('a', 'b', 2)")).toBe("bba");
        expect(evaluateExpr("'aaa'.replace('a', 'b')")).toBe("bbb");
    });

    test("title() capitalises non-ASCII letters", () => {
        expect(evaluateExpr("'éa'.title()")).toBe("Éa");
        expect(evaluateExpr("'ñandú test'.title()")).toBe("Ñandú Test");
        expect(evaluateExpr("'hello world-foo 2x'.title()")).toBe("Hello World-Foo 2X");
        expect(evaluateExpr('"it\'s a test".title()')).toBe("It'S A Test");
    });

    test("len() answers for sized values only", () => {
        expect(() => evaluateExpr("len(datetime.date(2020, 1, 1))")).toThrow(
            /has no len\(\)/,
        );
        expect(() => evaluateExpr("len(1)")).toThrow(/has no len\(\)/);
        expect(evaluateExpr("len({'a': 1, 'b': 2})")).toBe(2);
        expect(evaluateExpr("len([1, 2, 3])")).toBe(3);
        expect(evaluateExpr("len('abc')")).toBe(3);
        expect(evaluateExpr("len(set([1, 2]))")).toBe(2);
    });
});

describe("chained comparisons", () => {
    test("the middle operand is evaluated exactly once", () => {
        let reads = 0;
        const context = {
            get b() {
                reads++;
                return 2;
            },
        };
        expect(evaluateExpr("1 < b < 3", context)).toBe(true);
        expect(reads).toBe(1);
    });

    test("evaluation short-circuits on the first false comparison", () => {
        let reads = 0;
        const context = {
            get tail() {
                reads++;
                return 5;
            },
        };
        expect(evaluateExpr("1 < 0 < tail", context)).toBe(false);
        expect(reads).toBe(0);
    });

    test("results match CPython", () => {
        expect(evaluateExpr("1 < 2 < 3")).toBe(true);
        expect(evaluateExpr("1 < 3 < 2")).toBe(false);
        expect(evaluateExpr("3 < 2 < 1")).toBe(false);
        expect(evaluateExpr("1 < 2 <= 2 < 3")).toBe(true);
        expect(evaluateExpr("1 == 1 == 1")).toBe(true);
        expect(evaluateExpr("1 == 1 == 2")).toBe(false);
        expect(evaluateExpr("1 in [1, 2] and 2 not in [1]")).toBe(true);
        expect(evaluateExpr("'a' < 'b' < 'c'")).toBe(true);
    });

    test("the expression survives a round trip through formatAST", () => {
        for (const expr of ["1 < 2 < 3", "a < b <= c", "a == b != c"]) {
            expect(formatAST(parseExpr(expr))).toBe(expr);
        }
        expect(formatAST(parseExpr("(1 < 2 < 3) and x"))).toBe("1 < 2 < 3 and x");
    });

    test("a lone `not` cannot continue a chain", () => {
        expect(() => parseExpr("1 < 2 not 3")).toThrow();
    });
});

describe("the AST cache hands out immutable trees", () => {
    test("a cached AST is deeply frozen", () => {
        const ast = /** @type {any} */ (parseExpr("[('a', '=', 1)]"));
        expect(Object.isFrozen(ast)).toBe(true);
        expect(Object.isFrozen(ast.value)).toBe(true);
        expect(Object.isFrozen(ast.value[0])).toBe(true);
        expect(Object.isFrozen(ast.value[0].value[0])).toBe(true);
    });

    test("the same expression yields the same object, and writing to it throws", () => {
        const ast = /** @type {any} */ (parseExpr("a + 1"));
        expect(parseExpr("a + 1")).toBe(/** @type {any} */ (ast));
        expect(() => {
            ast.op = "-";
        }).toThrow(/read only|not extensible/);
    });
});

describe("py_js refuses arguments CPython refuses", () => {
    test("the no-argument str methods take no arguments", () => {
        for (const method of ["lower", "upper", "capitalize", "title"]) {
            expect(evaluateExpr(`'aBc'.${method}()`)).toBeOfType("string");
            expect(() => evaluateExpr(`'aBc'.${method}(1)`)).toThrow();
            expect(() => evaluateExpr(`'aBc'.${method}('x')`)).toThrow();
            expect(() => evaluateExpr(`'aBc'.${method}(nope=1)`)).toThrow();
        }
    });

    test("the no-argument str methods still answer correctly", () => {
        expect(evaluateExpr("'aBc'.lower()")).toBe("abc");
        expect(evaluateExpr("'aBc'.upper()")).toBe("ABC");
        expect(evaluateExpr("'aBc dEf'.capitalize()")).toBe("Abc def");
        expect(evaluateExpr("'aBc dEf'.title()")).toBe("Abc Def");
    });

    test("methods that do take arguments still bind them", () => {
        expect(evaluateExpr("'a,b'.split(',')")).toEqual(["a", "b"]);
        expect(evaluateExpr("' a '.strip()")).toBe("a");
        expect(evaluateExpr("'abc'.startswith(('x', 'a'))")).toBe(true);
        expect(evaluateExpr("{'a': 1}.get('x', {'b': 2})")).toEqual({ b: 2 });
    });
});
