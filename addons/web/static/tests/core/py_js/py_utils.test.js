// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr, formatAST, parseExpr } from "@web/core/py_js/py";
import { PyDate, PyDateTime, PyTime } from "@web/core/py_js/py_date";
import { toPyValue } from "@web/core/py_js/py_utils";

const checkAST = (expr, message = expr) => {
    const ast = parseExpr(expr);
    const str = formatAST(ast);
    if (str !== expr) {
        throw new Error(`mismatch: ${str} !== ${expr} (${message});`);
    }
    return true;
};

describe.current.tags("headless");

describe("formatAST", () => {
    test("basic values", () => {
        expect(checkAST("1", "number value")).toBe(true);
        expect(checkAST("1.4", "float value")).toBe(true);
        expect(checkAST("-12", "negative number value")).toBe(true);
        expect(checkAST("True", "boolean")).toBe(true);
        expect(checkAST(`"some string"`, "a string")).toBe(true);
        expect(checkAST("None", "None")).toBe(true);
    });

    test("dictionary", () => {
        expect(checkAST("{}", "empty dictionary")).toBe(true);
        expect(checkAST(`{"a": 1}`, "dictionary with a single key")).toBe(true);
        expect(checkAST(`d["a"]`, "get a value in a dictionary")).toBe(true);
    });

    test("list", () => {
        expect(checkAST("[]", "empty list")).toBe(true);
        expect(checkAST("[1]", "list with one value")).toBe(true);
        expect(checkAST("[1, 2]", "list with two values")).toBe(true);
    });

    test("tuple", () => {
        expect(checkAST("()", "empty tuple")).toBe(true);
        expect(checkAST("(1, 2)", "basic tuple")).toBe(true);
    });

    test("simple arithmetic", () => {
        expect(checkAST("1 + 2", "addition")).toBe(true);
        expect(checkAST("+(1 + 2)", "other addition, prefix")).toBe(true);
        expect(checkAST("1 - 2", "subtraction")).toBe(true);
        expect(checkAST("-1 - 2", "other subtraction")).toBe(true);
        expect(checkAST("-(1 + 2)", "other subtraction")).toBe(true);
        expect(checkAST("1 + 2 + 3", "addition of 3 integers")).toBe(true);
        expect(checkAST("a + b", "addition of two variables")).toBe(true);
        expect(checkAST("42 % 5", "modulo operator")).toBe(true);
        expect(checkAST("a * 10", "multiplication")).toBe(true);
        expect(checkAST("a ** 10", "**")).toBe(true);
        expect(checkAST("~10", "bitwise not")).toBe(true);
        expect(checkAST("~(10 + 3)", "bitwise not")).toBe(true);
        expect(checkAST("a * (1 + 2)", "multiplication and addition")).toBe(true);
        expect(checkAST("(a + b) * 43", "addition and multiplication")).toBe(true);
        expect(checkAST("a // 10", "number division")).toBe(true);
    });

    test("boolean operators", () => {
        expect(checkAST("True and False", "boolean operator")).toBe(true);
        expect(checkAST("True or False", "boolean operator or")).toBe(true);
        expect(
            checkAST("(True or False) and False", "boolean operators and and or"),
        ).toBe(true);
        expect(checkAST("not False", "not prefix")).toBe(true);
        expect(checkAST("not foo", "not prefix with variable")).toBe(true);
        expect(checkAST("not a in b", "not prefix with expression")).toBe(true);
    });

    test("conditional expression", () => {
        expect(checkAST("1 if a else 2")).toBe(true);
        expect(checkAST("[] if a else 2")).toBe(true);
    });

    test("other operators", () => {
        expect(checkAST("x == y", "== operator")).toBe(true);
        expect(checkAST("x != y", "!= operator")).toBe(true);
        expect(checkAST("x < y", "< operator")).toBe(true);
        expect(checkAST("x is y", "is operator")).toBe(true);
        expect(checkAST("x is not y", "is and not operator")).toBe(true);
        expect(checkAST("x in y", "in operator")).toBe(true);
        expect(checkAST("x not in y", "not in operator")).toBe(true);
    });

    test("equality", () => {
        expect(checkAST("a == b", "simple equality")).toBe(true);
    });

    test("strftime", () => {
        expect(checkAST(`time.strftime("%Y")`, "strftime with year")).toBe(true);
        expect(checkAST(`time.strftime("%Y") + "-01-30"`, "strftime with year")).toBe(
            true,
        );
        expect(
            checkAST(`time.strftime("%Y-%m-%d %H:%M:%S")`, "strftime with year"),
        ).toBe(true);
    });

    test("context_today", () => {
        expect(
            checkAST(`context_today().strftime("%Y-%m-%d")`, "context today call"),
        ).toBe(true);
    });

    test("function call", () => {
        expect(checkAST("td()", "simple call")).toBe(true);
        expect(checkAST("td(a, b, c)", "simple call with args")).toBe(true);
        expect(checkAST("td(days = 1)", "simple call with kwargs")).toBe(true);
        expect(checkAST("f(1, 2, days = 1)", "mixing args and kwargs")).toBe(true);
        expect(checkAST("str(td(2))", "function call in function call")).toBe(true);
    });

    test("various expressions", () => {
        expect(checkAST("(a - b).days", "subtraction and .days")).toBe(true);
        expect(checkAST("a + day == date(2002, 3, 3)")).toBe(true);
        const expr = `[("type", "=", "in"), ("day", "<=", time.strftime("%Y-%m-%d")), ("day", ">", (context_today() - datetime.timedelta(days = 15)).strftime("%Y-%m-%d"))]`;
        expect(checkAST(expr)).toBe(true);
    });

    test("escaping support", () => {
        expect(evaluateExpr(String.raw`"\x61"`)).toBe("a", { message: "hex escapes" });
        expect(evaluateExpr(String.raw`"\\abc"`)).toBe(String.raw`\abc`, {
            message: "escaped backslash",
        });
        expect(checkAST(String.raw`"\\abc"`, "escaped backslash AST check")).toBe(true);
        const a = String.raw`'foo\\abc"\''`;
        const b = formatAST(parseExpr(formatAST(parseExpr(a))));
        // Our repr uses JSON.stringify which always uses double quotes,
        // whereas Python's repr is single-quote-biased: strings are repr'd
        // using single quote delimiters *unless* they contain single quotes and
        // no double quotes, then they're delimited with double quotes.
        expect(b).toBe(String.raw`"foo\\abc\"'"`);
    });

    test("null value", () => {
        expect(formatAST(toPyValue(null))).toBe("None");
    });

    test("associativity survives the round-trip", () => {
        // Left-associative operators: an equal-precedence RIGHT child must
        // keep its parentheses, otherwise re-parsing regroups the expression
        // and changes its value.
        expect(checkAST("a - (b - c)", "right-nested subtraction")).toBe(true);
        expect(checkAST("a / (b / c)", "right-nested division")).toBe(true);
        expect(checkAST("a % (b % c)", "right-nested modulo")).toBe(true);
        expect(checkAST("a // (b // c)", "right-nested floor division")).toBe(true);
        expect(
            evaluateExpr(formatAST(parseExpr("total - (tax - discount)")), {
                total: 100,
                tax: 20,
                discount: 5,
            }),
        ).toBe(85);
        // `**` is right-associative: an equal-precedence LEFT child must keep
        // its parentheses.
        expect(checkAST("(a ** b) ** c", "left-nested power")).toBe(true);
        expect(evaluateExpr(formatAST(parseExpr("(2**3)**2")))).toBe(64);
        expect(evaluateExpr(formatAST(parseExpr("2**3**2")))).toBe(512);
        // Comparators are non-associative: `(a < b) < c` and the chained
        // `a < b < c` are different expressions.
        expect(checkAST("(a < b) < c", "nested comparison")).toBe(true);
    });

    test("low-precedence sub-expressions keep their parentheses", () => {
        // A conditional expression has the lowest precedence in Python.
        expect(checkAST("1 + (2 if x else 3)", "ternary in addition")).toBe(true);
        expect(checkAST("(a if x else b) if y else c", "ternary in ternary")).toBe(
            true,
        );
        expect(
            evaluateExpr(formatAST(parseExpr("1 + (2 if x else 3)")), { x: false }),
        ).toBe(4);
        // Unary operators bind looser than `**`.
        expect(checkAST("(-a) ** 2", "unary minus in power")).toBe(true);
        expect(evaluateExpr(formatAST(parseExpr("(-2) ** 2")))).toBe(4);
    });

    test("one-element tuple keeps its trailing comma", () => {
        expect(formatAST(parseExpr("(1,)"))).toBe("(1,)");
        expect(evaluateExpr(formatAST(parseExpr("(1,)")))).toEqual([1]);
    });

    test("dictionary keys are escaped", () => {
        expect(formatAST(parseExpr(String.raw`{'a"b': 1}`))).toBe(
            String.raw`{"a\"b": 1}`,
        );
        expect(checkAST(String.raw`{"a\"b": 1}`, "dict key with a double quote")).toBe(
            true,
        );
    });

    test("long list is not parenthesized by element position", () => {
        // `.map(formatAST)` used to pass the array index as the binding
        // power, parenthesizing low-bp elements past index 30 ("or" bp is 30).
        const numbers = Array.from({ length: 32 }, (_, i) => String(i));
        const expr = `[${[...numbers, "a or b"].join(", ")}]`;
        expect(checkAST(expr, "33-element list with trailing boolean op")).toBe(true);
    });
});

describe("toPyValue", () => {
    test("toPyValue a string", () => {
        const ast = toPyValue("test");
        expect(ast.type).toBe(1);
        expect(ast.value).toBe("test");
        expect(formatAST(ast)).toBe('"test"');
    });

    test("toPyValue a number", () => {
        const ast = toPyValue(1);
        expect(ast.type).toBe(0);
        expect(ast.value).toBe(1);
        expect(formatAST(ast)).toBe("1");
    });

    test("toPyValue a boolean", () => {
        let ast = toPyValue(true);
        expect(ast.type).toBe(2);
        expect(ast.value).toBe(true);
        expect(formatAST(ast)).toBe("True");

        ast = toPyValue(false);
        expect(ast.type).toBe(2);
        expect(ast.value).toBe(false);
        expect(formatAST(ast)).toBe("False");
    });

    test("toPyValue a object", () => {
        const ast = toPyValue({ a: 1 });
        expect(ast.type).toBe(11);
        expect("a" in ast.value).toBe(true);
        expect(["type", "value"].every((prop) => prop in ast.value.a)).toBe(true);
        expect(ast.value.a.type).toBe(0);
        expect(ast.value.a.value).toBe(1);
        expect(formatAST(ast)).toBe('{"a": 1}');
    });

    // Date-like values are serialized EAGERLY: the node is a genuine string
    // AST (it used to smuggle the Py* instance as `value`, which relied on
    // formatAST's JSON.stringify calling toJSON). formatAST output unchanged.
    test("toPyValue a date", () => {
        const date = new Date(Date.UTC(2000, 0, 1));
        const ast = toPyValue(date);
        expect(ast.type).toBe(1);
        const expectedValue = PyDateTime.convertDate(date);
        expect(ast.value).toBe(expectedValue.strftime("%Y-%m-%d %H:%M:%S"));
        expect(formatAST(ast)).toBe(JSON.stringify(expectedValue));
    });

    test("toPyValue a dateime", () => {
        const datetime = new Date(Date.UTC(2000, 0, 1, 1, 0, 0, 0));
        const ast = toPyValue(datetime);
        expect(ast.type).toBe(1);
        const expectedValue = PyDateTime.convertDate(datetime);
        expect(ast.value).toBe(expectedValue.strftime("%Y-%m-%d %H:%M:%S"));
        expect(formatAST(ast)).toBe(JSON.stringify(expectedValue));
    });

    test("toPyValue a PyDate", () => {
        const value = new PyDate(2000, 1, 1);
        const ast = toPyValue(value);
        expect(ast.type).toBe(1);
        expect(ast.value).toBe("2000-01-01");
        expect(formatAST(ast)).toBe(JSON.stringify(value));
    });

    test("toPyValue a PyDateTime", () => {
        const value = new PyDateTime(2000, 1, 1, 1, 0, 0, 0);
        const ast = toPyValue(value);
        expect(ast.type).toBe(1);
        expect(ast.value).toBe("2000-01-01 01:00:00");
        expect(formatAST(ast)).toBe(JSON.stringify(value));
    });

    test("toPyValue a PyTime", () => {
        const value = PyTime.create(11, 45, 15);
        const ast = toPyValue(value);
        expect(ast.type).toBe(1);
        expect(ast.value).toBe("11:45:15");
        expect(formatAST(ast)).toBe(JSON.stringify(value));
    });
});
