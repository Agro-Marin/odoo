// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { Domain } from "@web/core/domain";
import { PyDate } from "@web/core/py_js/py_date";

describe.current.tags("headless");

describe("Basic Properties", () => {
    test("empty", () => {
        expect(new Domain([]).contains({})).toBe(true);
        expect(new Domain([]).toString()).toBe("[]");
        expect(new Domain([]).toList()).toEqual([]);
    });

    test("constructing from an existing Domain reuses its AST (no string round-trip, no source corruption)", () => {
        const src = new Domain(`["|", ("a", "=", 1), ("b", "!=", false)]`);
        const copy = new Domain(src);
        // Same semantics as the source (the constructor no longer round-trips
        // through toString()+parseExpr).
        expect(copy.toString()).toBe(src.toString());
        expect(copy.toList({})).toEqual(src.toList({}));
        // The copy owns its AST value array: a mutating derivation (not() does
        // an in-place unshift on `new Domain(src)`) must not corrupt the source.
        const before = src.toString();
        Domain.not(src);
        expect(src.toString()).toBe(before);
    });

    test("undefined domain", () => {
        expect(new Domain(undefined).contains({})).toBe(true);
        expect(new Domain(undefined).toString()).toBe("[]");
        expect(new Domain(undefined).toList()).toEqual([]);
    });

    test("simple condition", () => {
        expect(new Domain([["a", "=", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "=", 3]]).contains({ a: 5 })).toBe(false);
        expect(new Domain([["a", "=", 3]]).toString()).toBe(`[("a", "=", 3)]`);
        expect(new Domain([["a", "=", 3]]).toList()).toEqual([["a", "=", 3]]);
    });

    test("can be created from domain", () => {
        const domain = new Domain([["a", "=", 3]]);
        expect(new Domain(domain).toString()).toBe(`[("a", "=", 3)]`);
    });

    test("basic", () => {
        const record = {
            a: 3,
            group_method: "line",
            select1: "day",
            rrule_type: "monthly",
        };
        expect(new Domain([["a", "=", 3]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=", 5]]).contains(record)).toBe(false);
        expect(new Domain([["group_method", "!=", "count"]]).contains(record)).toBe(
            true,
        );
        expect(
            new Domain([
                ["select1", "=", "day"],
                ["rrule_type", "=", "monthly"],
            ]).contains(record),
        ).toBe(true);
    });

    test("support of '=?' operator", () => {
        const record = { a: 3 };
        expect(new Domain([["a", "=?", null]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=?", false]]).contains(record)).toBe(true);
        expect(new Domain(["!", ["a", "=?", false]]).contains(record)).toBe(false);
        expect(new Domain([["a", "=?", 1]]).contains(record)).toBe(false);
        expect(new Domain([["a", "=?", 3]]).contains(record)).toBe(true);
        expect(new Domain(["!", ["a", "=?", 3]]).contains(record)).toBe(false);
    });

    test("'any'/'not any'/hierarchy operators in contains()", () => {
        // No access to related/hierarchy records here, so `any`, `child_of`,
        // `parent_of` always match, and `not any` is their strict dual (never matches).
        const value = [["id", "=", 1]];
        expect(new Domain([["line_ids", "any", value]]).contains({})).toBe(true);
        expect(new Domain([["parent_id", "child_of", 1]]).contains({})).toBe(true);
        expect(new Domain([["parent_id", "parent_of", 1]]).contains({})).toBe(true);
        // `not any` never matches, and agrees with `!(x any y)`.
        expect(new Domain([["line_ids", "not any", value]]).contains({})).toBe(false);
        expect(new Domain(["!", ["line_ids", "any", value]]).contains({})).toBe(
            new Domain([["line_ids", "not any", value]]).contains({}),
        );
    });

    test("or", () => {
        const currentDomain = [
            "|",
            ["section_id", "=", 42],
            "|",
            ["user_id", "=", 3],
            ["member_ids", "in", [3]],
        ];
        const record = {
            section_id: null,
            user_id: null,
            member_ids: null,
        };
        expect(new Domain(currentDomain).contains({ ...record, section_id: 42 })).toBe(
            true,
        );
        expect(new Domain(currentDomain).contains({ ...record, user_id: 3 })).toBe(
            true,
        );
        expect(new Domain(currentDomain).contains({ ...record, member_ids: 3 })).toBe(
            true,
        );
    });

    test("and", () => {
        const domain = new Domain([
            "&",
            "&",
            ["a", "=", 1],
            ["b", "=", 2],
            ["c", "=", 3],
        ]);

        expect(domain.contains({ a: 1, b: 2, c: 3 })).toBe(true);
        expect(domain.contains({ a: -1, b: 2, c: 3 })).toBe(false);
        expect(domain.contains({ a: 1, b: -1, c: 3 })).toBe(false);
        expect(domain.contains({ a: 1, b: 2, c: -1 })).toBe(false);
    });

    test("not", () => {
        const record = {
            a: 5,
            group_method: "line",
        };
        expect(new Domain(["!", ["a", "=", 3]]).contains(record)).toBe(true);
        expect(new Domain(["!", ["group_method", "=", "count"]]).contains(record)).toBe(
            true,
        );
    });

    test("inequalities never match unset fields", () => {
        // SQL semantics: comparisons on NULL are falsy, while raw JS would
        // evaluate `false < 5` as true. Known divergence: a numeric field
        // whose client value is `false` is excluded even where the server
        // stores an actual 0 (0 < 5 matches server-side, NULL does not).
        for (const op of ["<", "<=", ">", ">="]) {
            expect(new Domain([["a", op, 5]]).contains({ a: false })).toBe(false);
            expect(new Domain([["a", op, 5]]).contains({})).toBe(false);
        }
        expect(new Domain([["a", "<", 5]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "<=", 0]]).contains({ a: 0 })).toBe(true);
        expect(new Domain([["a", ">", 5]]).contains({ a: 6 })).toBe(true);
        expect(new Domain([["a", ">=", 5]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", ">", 5]]).contains({ a: 3 })).toBe(false);
    });

    test("like, =like, ilike, =ilike and not likes", () => {
        expect.assertions(34);

        expect(new Domain([["a", "like", "value"]]).contains({ a: "value" })).toBe(
            true,
        );
        expect(new Domain([["a", "like", "value"]]).contains({ a: "some value" })).toBe(
            true,
        );
        expect(
            new Domain([["a", "like", "value"]]).contains({ a: "Some Value" }),
        ).not.toBe(true);
        expect(new Domain([["a", "like", "value"]]).contains({ a: false })).toBe(false);

        expect(new Domain([["a", "=like", "%value"]]).contains({ a: "value" })).toBe(
            true,
        );
        expect(
            new Domain([["a", "=like", "%value"]]).contains({ a: "some value" }),
        ).toBe(true);
        expect(
            new Domain([["a", "=like", "%value"]]).contains({ a: "Some Value" }),
        ).not.toBe(true);
        expect(new Domain([["a", "=like", "%value"]]).contains({ a: false })).toBe(
            false,
        );

        expect(new Domain([["a", "ilike", "value"]]).contains({ a: "value" })).toBe(
            true,
        );
        expect(
            new Domain([["a", "ilike", "value"]]).contains({ a: "some value" }),
        ).toBe(true);
        expect(
            new Domain([["a", "ilike", "value"]]).contains({ a: "Some Value" }),
        ).toBe(true);
        expect(new Domain([["a", "ilike", "value"]]).contains({ a: false })).toBe(
            false,
        );

        expect(new Domain([["a", "=ilike", "%value"]]).contains({ a: "value" })).toBe(
            true,
        );
        expect(
            new Domain([["a", "=ilike", "%value"]]).contains({ a: "some value" }),
        ).toBe(true);
        expect(
            new Domain([["a", "=ilike", "%value"]]).contains({ a: "Some Value" }),
        ).toBe(true);
        expect(new Domain([["a", "=ilike", "%value"]]).contains({ a: false })).toBe(
            false,
        );

        expect(
            new Domain([["a", "not like", "value"]]).contains({ a: "value" }),
        ).not.toBe(true);
        expect(
            new Domain([["a", "not like", "value"]]).contains({ a: "some value" }),
        ).not.toBe(true);
        expect(
            new Domain([["a", "not like", "value"]]).contains({ a: "Some Value" }),
        ).toBe(true);
        expect(
            new Domain([["a", "not like", "value"]]).contains({ a: "something" }),
        ).toBe(true);
        expect(
            new Domain([["a", "not like", "value"]]).contains({ a: "Something" }),
        ).toBe(true);
        expect(new Domain([["a", "not like", "value"]]).contains({ a: false })).toBe(
            true,
        );

        expect(
            new Domain([["a", "not ilike", "value"]]).contains({ a: "value" }),
        ).not.toBe(true);
        expect(
            new Domain([["a", "not ilike", "value"]]).contains({ a: "some value" }),
        ).toBe(false);
        expect(
            new Domain([["a", "not ilike", "value"]]).contains({ a: "Some Value" }),
        ).toBe(false);
        expect(
            new Domain([["a", "not ilike", "value"]]).contains({ a: "something" }),
        ).toBe(true);
        expect(
            new Domain([["a", "not ilike", "value"]]).contains({ a: "Something" }),
        ).toBe(true);
        expect(new Domain([["a", "not ilike", "value"]]).contains({ a: false })).toBe(
            true,
        );

        expect(
            new Domain([["a", "not =like", "%value"]]).contains({ a: "some value" }),
        ).toBe(false);
        expect(
            new Domain([["a", "not =like", "%value"]]).contains({ a: "Some Value" }),
        ).not.toBe(false);

        expect(
            new Domain([["a", "not =ilike", "%value"]]).contains({ a: "value" }),
        ).toBe(false);
        expect(
            new Domain([["a", "not =ilike", "%value"]]).contains({ a: "some value" }),
        ).toBe(false);
        expect(
            new Domain([["a", "not =ilike", "%value"]]).contains({ a: "Some Value" }),
        ).toBe(false);
        expect(new Domain([["a", "not =ilike", "%value"]]).contains({ a: false })).toBe(
            true,
        );
    });

    test("like-family: an absent field never matches (no 'undefined' coercion)", () => {
        // A record missing the field entirely (fieldValue === undefined) must
        // behave like an unset field, NOT be coerced to the string "undefined"
        // and matched against the pattern.
        expect(new Domain([["name", "ilike", "und"]]).contains({})).toBe(false);
        expect(new Domain([["name", "like", "und"]]).contains({})).toBe(false);
        expect(new Domain([["name", "=ilike", "unde%"]]).contains({})).toBe(false);
        expect(new Domain([["name", "=like", "unde%"]]).contains({})).toBe(false);
        // Negated forms match an absent field (the pattern is not present).
        expect(new Domain([["name", "not ilike", "nde"]]).contains({})).toBe(true);
        expect(new Domain([["name", "not like", "nde"]]).contains({})).toBe(true);
    });

    test("complex domain", () => {
        const domain = new Domain([
            "&",
            "!",
            ["a", "=", 1],
            "|",
            ["a", "=", 2],
            ["a", "=", 3],
        ]);

        expect(domain.contains({ a: 1 })).toBe(false);
        expect(domain.contains({ a: 2 })).toBe(true);
        expect(domain.contains({ a: 3 })).toBe(true);
        expect(domain.contains({ a: 4 })).toBe(false);
    });

    test("toList", () => {
        expect(new Domain([]).toList()).toEqual([]);
        expect(new Domain([["a", "=", 3]]).toList()).toEqual([["a", "=", 3]]);
        expect(
            new Domain([
                ["a", "=", 3],
                ["b", "!=", "4"],
            ]).toList(),
        ).toEqual(["&", ["a", "=", 3], ["b", "!=", "4"]]);
        expect(new Domain(["!", ["a", "=", 3]]).toList()).toEqual(["!", ["a", "=", 3]]);
    });

    test("flat implicit-AND normalization scales (O(N)) and stays correct", () => {
        // Regression for the O(N)-rewrite of normalizeDomainAST: N leaves with
        // no explicit operator normalize to (N-1) leading "&" then the leaves in
        // order. Exercised at a size that would be painfully O(N^2) under the
        // old per-segment unshift.
        const N = 500;
        const leaves = Array.from({ length: N }, (_, i) => [`f${i}`, "=", i]);
        const dom = new Domain(leaves);
        const ast = dom.ast.value;
        expect(ast.length).toBe(2 * N - 1);
        // First N-1 tokens are "&" operators...
        expect(ast.slice(0, N - 1).every((n) => n.value === "&")).toBe(true);
        // ...followed by the N leaves in their original order.
        expect(ast[N - 1].value[0].value).toBe("f0");
        expect(ast.at(-1).value[0].value).toBe(`f${N - 1}`);
        // And it still evaluates as a plain AND of all leaves.
        const record = Object.fromEntries(leaves.map(([f, , v]) => [f, v]));
        expect(dom.contains(record)).toBe(true);
        record.f7 = 999;
        expect(dom.contains(record)).toBe(false);
    });

    test("toString", () => {
        expect(new Domain([]).toString()).toBe(`[]`);
        expect(new Domain([["a", "=", 3]]).toString()).toBe(`[("a", "=", 3)]`);
        expect(
            new Domain([
                ["a", "=", 3],
                ["b", "!=", "4"],
            ]).toString(),
        ).toBe(`["&", ("a", "=", 3), ("b", "!=", "4")]`);
        expect(new Domain(["!", ["a", "=", 3]]).toString()).toBe(
            `["!", ("a", "=", 3)]`,
        );
        expect(new Domain([["name", "=", null]]).toString()).toBe(
            '[("name", "=", None)]',
        );
        expect(new Domain([["name", "=", false]]).toString()).toBe(
            '[("name", "=", False)]',
        );
        expect(new Domain([["name", "=", true]]).toString()).toBe(
            '[("name", "=", True)]',
        );
        expect(new Domain([["name", "=", "null"]]).toString()).toBe(
            '[("name", "=", "null")]',
        );
        expect(new Domain([["name", "=", "false"]]).toString()).toBe(
            '[("name", "=", "false")]',
        );
        expect(new Domain([["name", "=", "true"]]).toString()).toBe(
            '[("name", "=", "true")]',
        );
        expect(new Domain().toString()).toBe("[]");
        expect(new Domain([["name", "in", [true, false]]]).toString()).toBe(
            '[("name", "in", [True, False])]',
        );
        expect(new Domain([["name", "in", [null]]]).toString()).toBe(
            '[("name", "in", [None])]',
        );
        expect(new Domain([["name", "in", ["foo", "bar"]]]).toString()).toBe(
            '[("name", "in", ["foo", "bar"])]',
        );
        expect(new Domain([["name", "in", [1, 2]]]).toString()).toBe(
            '[("name", "in", [1, 2])]',
        );
        expect(
            new Domain(["&", ["name", "=", "foo"], ["type", "=", "bar"]]).toString(),
        ).toBe('["&", ("name", "=", "foo"), ("type", "=", "bar")]');
        expect(
            new Domain(["|", ["name", "=", "foo"], ["type", "=", "bar"]]).toString(),
        ).toBe('["|", ("name", "=", "foo"), ("type", "=", "bar")]');
        expect(new Domain().toString()).toBe("[]");

        // string domains are only reformatted
        expect(new Domain('[("name","ilike","foo")]').toString()).toBe(
            '[("name", "ilike", "foo")]',
        );
    });

    test("toJson", () => {
        expect(new Domain([]).toJson()).toEqual([]);
        expect(new Domain("[]").toJson()).toEqual([]);
        expect(new Domain([["a", "=", 3]]).toJson()).toEqual([["a", "=", 3]]);
        expect(new Domain('[("a", "=", 3)]').toJson()).toEqual([["a", "=", 3]]);
        expect(new Domain('[("user_id", "=", uid)]').toJson()).toBe(
            '[("user_id", "=", uid)]',
        );
        expect(new Domain('[("date", "=", context_today())]').toJson()).toBe(
            '[("date", "=", context_today())]',
        );
    });

    test("implicit &", () => {
        const domain = new Domain([
            ["a", "=", 3],
            ["b", "=", 4],
        ]);
        expect(domain.contains({})).toBe(false);
        expect(domain.contains({ a: 3, b: 4 })).toBe(true);
        expect(domain.contains({ a: 3, b: 5 })).toBe(false);
    });

    test("comparison operators", () => {
        expect(new Domain([["a", "=", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "=", 3]]).contains({ a: 4 })).toBe(false);
        expect(new Domain([["a", "=", 3]]).toString()).toBe(`[("a", "=", 3)]`);
        expect(new Domain([["a", "==", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "==", 3]]).contains({ a: 4 })).toBe(false);
        expect(new Domain([["a", "==", 3]]).toString()).toBe(`[("a", "==", 3)]`);
        expect(new Domain([["a", "!=", 3]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", "!=", 3]]).contains({ a: 4 })).toBe(true);
        expect(new Domain([["a", "!=", 3]]).toString()).toBe(`[("a", "!=", 3)]`);
        expect(new Domain([["a", "<>", 3]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", "<>", 3]]).contains({ a: 4 })).toBe(true);
        expect(new Domain([["a", "<>", 3]]).toString()).toBe(`[("a", "<>", 3)]`);
        expect(new Domain([["a", "<", 3]]).contains({ a: 5 })).toBe(false);
        expect(new Domain([["a", "<", 3]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", "<", 3]]).contains({ a: 2 })).toBe(true);
        expect(new Domain([["a", "<", 3]]).toString()).toBe(`[("a", "<", 3)]`);
        expect(new Domain([["a", "<=", 3]]).contains({ a: 5 })).toBe(false);
        expect(new Domain([["a", "<=", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "<=", 3]]).contains({ a: 2 })).toBe(true);
        expect(new Domain([["a", "<=", 3]]).toString()).toBe(`[("a", "<=", 3)]`);
        expect(new Domain([["a", ">", 3]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", ">", 3]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", ">", 3]]).contains({ a: 2 })).toBe(false);
        expect(new Domain([["a", ">", 3]]).toString()).toBe(`[("a", ">", 3)]`);
        expect(new Domain([["a", ">=", 3]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", ">=", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", ">=", 3]]).contains({ a: 2 })).toBe(false);
        expect(new Domain([["a", ">=", 3]]).toString()).toBe(`[("a", ">=", 3)]`);
    });

    test("other operators", () => {
        expect(new Domain([["a", "in", 3]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "in", [1, 2, 3]]]).contains({ a: 3 })).toBe(true);
        expect(new Domain([["a", "in", [1, 2, 3]]]).contains({ a: [3] })).toBe(true);
        expect(new Domain([["a", "in", 3]]).contains({ a: 5 })).toBe(false);
        expect(new Domain([["a", "in", [1, 2, 3]]]).contains({ a: 5 })).toBe(false);
        expect(new Domain([["a", "in", [1, 2, 3]]]).contains({ a: [5] })).toBe(false);
        expect(new Domain([["a", "not in", 3]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", "not in", [1, 2, 3]]]).contains({ a: 3 })).toBe(false);
        expect(new Domain([["a", "not in", [1, 2, 3]]]).contains({ a: [3] })).toBe(
            false,
        );
        expect(new Domain([["a", "not in", 3]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", "not in", [1, 2, 3]]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", "not in", [1, 2, 3]]]).contains({ a: [5] })).toBe(
            true,
        );
        expect(new Domain([["a", "like", "abc"]]).contains({ a: "abc" })).toBe(true);
        expect(new Domain([["a", "like", "abc"]]).contains({ a: "def" })).toBe(false);
        expect(new Domain([["a", "=like", "abc"]]).contains({ a: "abc" })).toBe(true);
        expect(new Domain([["a", "=like", "abc"]]).contains({ a: "def" })).toBe(false);
        expect(new Domain([["a", "ilike", "abc"]]).contains({ a: "abc" })).toBe(true);
        expect(new Domain([["a", "ilike", "abc"]]).contains({ a: "def" })).toBe(false);
        expect(new Domain([["a", "=ilike", "abc"]]).contains({ a: "abc" })).toBe(true);
        expect(new Domain([["a", "=ilike", "abc"]]).contains({ a: "def" })).toBe(false);
    });

    test("creating a domain with a string expression", () => {
        expect(new Domain(`[('a', '>=', 3)]`).toString()).toBe(`[("a", ">=", 3)]`);
        expect(new Domain(`[('a', '>=', 3)]`).contains({ a: 5 })).toBe(true);
    });

    test("can evaluate a python expression", () => {
        expect(new Domain(`[('date', '!=', False)]`).toList()).toEqual([
            ["date", "!=", false],
        ]);
        expect(new Domain(`[('date', '!=', False)]`).toList()).toEqual([
            ["date", "!=", false],
        ]);
        expect(new Domain(`[('date', '!=', 1 + 2)]`).toString()).toBe(
            `[("date", "!=", 1 + 2)]`,
        );
        expect(new Domain(`[('date', '!=', 1 + 2)]`).toList()).toEqual([
            ["date", "!=", 3],
        ]);
        expect(new Domain(`[('a', '==', 1 + 2)]`).contains({ a: 3 })).toBe(true);
        expect(new Domain(`[('a', '==', 1 + 2)]`).contains({ a: 2 })).toBe(false);
    });

    test("some expression with date stuff", () => {
        patchWithCleanup(PyDate, {
            today() {
                return new PyDate(2013, 4, 24);
            },
        });

        expect(
            new Domain(
                "[('date','>=', (context_today() - datetime.timedelta(days=30)).strftime('%Y-%m-%d'))]",
            ).toList(),
        ).toEqual([["date", ">=", "2013-03-25"]]);

        const domainList = new Domain(
            "[('date', '>=', context_today() - relativedelta(days=30))]",
        ).toList(); // domain creation using `parseExpr` function since the parameter is a string.

        expect(domainList[0][2]).toEqual(
            PyDate.create({ day: 25, month: 3, year: 2013 }),
            {
                message:
                    "The right item in the rule in the domain should be a PyDate object",
            },
        );
        expect(JSON.stringify(domainList)).toBe('[["date",">=","2013-03-25"]]');

        const domainList2 = new Domain(domainList).toList(); // domain creation using `toAST` function since the parameter is a list.
        // toPyValue serializes date-likes eagerly, so the PyDate round-trips
        // through the list form as its date string.
        expect(domainList2[0][2]).toBe("2013-03-25");
        expect(JSON.stringify(domainList2)).toBe('[["date",">=","2013-03-25"]]');
    });

    test("Check that there is no dependency between two domains", () => {
        const domain1 = new Domain(`[('date', '!=', False)]`);
        const domain2 = new Domain(domain1);
        expect(domain1.toString()).toBe(domain2.toString());

        domain2.ast.value.unshift({ type: 1, value: "!" });
        expect(domain1.toString()).not.toBe(domain2.toString());
    });

    test("TRUE and FALSE Domain", () => {
        expect(Domain.TRUE.contains({})).toBe(true);
        expect(Domain.FALSE.contains({})).toBe(false);

        expect(
            Domain.and([Domain.TRUE, new Domain([["a", "=", 3]])]).contains({ a: 3 }),
        ).toBe(true);
        expect(
            Domain.and([Domain.FALSE, new Domain([["a", "=", 3]])]).contains({ a: 3 }),
        ).toBe(false);
    });

    test("invalid domains should not succeed", () => {
        expect(() => new Domain(["|", ["hr_presence_state", "=", "absent"]])).toThrow(
            /invalid domain .* \(missing 1 segment/,
        );
        expect(
            () =>
                new Domain([
                    "|",
                    "|",
                    ["hr_presence_state", "=", "absent"],
                    ["attendance_state", "=", "checked_in"],
                ]),
        ).toThrow(/invalid domain .* \(missing 1 segment/);
        expect(
            () => new Domain(["|", "|", ["hr_presence_state", "=", "absent"]]),
        ).toThrow(/invalid domain .* \(missing 2 segment\(s\)/);
        expect(
            () => new Domain(["&", ["composition_mode", "!=", "mass_post"]]),
        ).toThrow(/invalid domain .* \(missing 1 segment/);
        expect(() => new Domain(["!"])).toThrow(
            /invalid domain .* \(missing 1 segment/,
        );
        expect(() => new Domain(`[(1, 2)]`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`[(1, 2, 3, 4)]`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`["a"]`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`[1]`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`[x]`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`[True]`)).toThrow(/Invalid domain AST/); // will possibly change with CHM work
        expect(() => new Domain(`[(x.=, "=", 1)]`)).toThrow(
            /Invalid domain representation/,
        );
        expect(() => new Domain(`[(+, "=", 1)]`)).toThrow(
            /Invalid domain representation/,
        );
        expect(() => new Domain([{}])).toThrow(/Invalid domain representation/);
        expect(() => new Domain([1])).toThrow(/Invalid domain representation/);
    });

    test("malformed positional domains throw on construction", () => {
        // A complete expression followed by a dangling operator is invalid
        // in prefix notation — the server parser raises for these too.
        expect(() => new Domain([["a", "=", 1], "&", ["b", "=", 2]])).toThrow(
            /invalid domain .* \(missing 1 segment/,
        );
        expect(() => new Domain(`[("a", "=", 1), "&", ("b", "=", 2)]`)).toThrow(
            /invalid domain .* \(missing 1 segment/,
        );
        expect(() => new Domain([["a", "=", 1], "!"])).toThrow(
            /invalid domain .* \(missing 1 segment/,
        );
        expect(() => new Domain([["a", "=", 1], ["b", "=", 2], "&"])).toThrow(
            /invalid domain .* \(missing 2 segment/,
        );
        // Mid-list operators that still receive their operands stay valid
        // (server parity): [A, "&", B, C] means A AND (B AND C).
        const domain = new Domain([["a", "=", 1], "&", ["b", "=", 2], ["c", "=", 3]]);
        expect(domain.toList()).toEqual([
            "&",
            ["a", "=", 1],
            "&",
            ["b", "=", 2],
            ["c", "=", 3],
        ]);
        expect(domain.contains({ a: 1, b: 2, c: 3 })).toBe(true);
        expect(domain.contains({ a: 1, b: 2, c: 4 })).toBe(false);
    });

    test("matching a malformed evaluated domain throws", () => {
        // Simulate a corrupted AST reaching the prefix stack machine: the
        // leftover operand must raise instead of silently matching only the
        // first segment.
        const leftover = new Domain(["&", ["a", "=", 1], ["b", "=", 2]]);
        leftover.ast.value.shift(); // drop the "&" -> evaluates to [A, B]
        expect(() => leftover.contains({ a: 1, b: 99 })).toThrow(
            /invalid domain \(unconsumed segment/,
        );
        const starved = new Domain(["&", ["a", "=", 1], ["b", "=", 2]]);
        starved.ast.value.pop(); // drop an operand -> evaluates to ["&", A]
        expect(() => starved.contains({ a: 1 })).toThrow(
            /invalid domain \(missing operand/,
        );
    });

    test("follow relations", () => {
        expect(
            new Domain([["partner.city", "ilike", "Bru"]]).contains({
                name: "Lucas",
                partner: {
                    city: "Bruxelles",
                },
            }),
        ).toBe(true);
        expect(
            new Domain([["partner.city.name", "ilike", "Bru"]]).contains({
                name: "Lucas",
                partner: {
                    city: {
                        name: "Bruxelles",
                    },
                },
            }),
        ).toBe(true);
    });

    test("Arrays comparison", () => {
        const domain = new Domain(["&", ["a", "==", []], ["b", "!=", []]]);

        expect(domain.contains({ a: [] })).toBe(true);
        expect(domain.contains({ a: [], b: [4] })).toBe(true);
        expect(domain.contains({ a: [1] })).toBe(false);
        expect(domain.contains({ b: [] })).toBe(false);
    });
});

// Client/server matching parity (matchCondition / operator handling)
describe("Matching parity", () => {
    test("Domain.not([]) is FALSE and matches nothing (no crash)", () => {
        // Empty domain is TRUE; server maps ~TRUE -> FALSE. The old code
        // produced the malformed ["!"] which crashed toString()/contains().
        expect(() => Domain.not([]).toString()).not.toThrow();
        expect(Domain.not([]).toString()).toBe('[(0, "=", 1)]');
        expect(Domain.not([]).contains({})).toBe(false);
        expect(Domain.not([]).contains({ a: 1 })).toBe(false);
        // A non-empty domain is still negated the usual way.
        expect(Domain.not([["a", "=", 1]]).toString()).toBe('["!", ("a", "=", 1)]');
    });

    test("'=?' is always-true for any falsy value (0, '', false, null)", () => {
        const record = { a: 5 };
        expect(new Domain([["a", "=?", 0]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=?", ""]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=?", false]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=?", null]]).contains(record)).toBe(true);
        // Truthy value: behaves like '='.
        expect(new Domain([["a", "=?", 5]]).contains(record)).toBe(true);
        expect(new Domain([["a", "=?", 3]]).contains(record)).toBe(false);
    });

    test("operators are matched case-insensitively", () => {
        expect(new Domain([["a", "IN", [1, 2, 3]]]).contains({ a: 2 })).toBe(true);
        expect(new Domain([["a", "IN", [1, 2, 3]]]).contains({ a: 9 })).toBe(false);
        expect(new Domain([["a", "LIKE", "ab"]]).contains({ a: "xabx" })).toBe(true);
        expect(new Domain([["a", "Not In", [1]]]).contains({ a: 2 })).toBe(true);
    });

    test("like: '_' wildcard, non-string value, and escaped '\\%'/'\\_'", () => {
        // '_' matches exactly one character.
        expect(new Domain([["a", "=like", "a_c"]]).contains({ a: "abc" })).toBe(true);
        expect(new Domain([["a", "=like", "a_c"]]).contains({ a: "abbc" })).toBe(false);
        // Non-string value must not crash escapeRegExp.
        expect(new Domain([["a", "like", 12]]).contains({ a: "x123" })).toBe(true);
        expect(new Domain([["a", "like", 12]]).contains({ a: "x13" })).toBe(false);
        // '%' remains a multi-char wildcard.
        expect(new Domain([["a", "=like", "a%c"]]).contains({ a: "abbbc" })).toBe(true);
        // Escaped '\%' / '\_' match literal '%' / '_'.
        expect(new Domain([["a", "=like", "a\\%c"]]).contains({ a: "a%c" })).toBe(true);
        expect(new Domain([["a", "=like", "a\\%c"]]).contains({ a: "abbc" })).toBe(
            false,
        );
        expect(new Domain([["a", "=like", "a\\_c"]]).contains({ a: "a_c" })).toBe(true);
        expect(new Domain([["a", "=like", "a\\_c"]]).contains({ a: "abc" })).toBe(
            false,
        );
    });

    test("'any' / 'not any' negation duality (always-match approximation)", () => {
        const sub = [["x", "=", 1]];
        expect(new Domain([["a", "any", sub]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", "not any", sub]]).contains({ a: 5 })).toBe(false);
        // !(x any y) is consistent with (x not any y).
        expect(new Domain(["!", ["a", "any", sub]]).contains({ a: 5 })).toBe(
            new Domain([["a", "not any", sub]]).contains({ a: 5 }),
        );
        // child_of / parent_of stay always-true.
        expect(new Domain([["a", "child_of", [1]]]).contains({ a: 5 })).toBe(true);
        expect(new Domain([["a", "parent_of", [1]]]).contains({ a: 5 })).toBe(true);
    });
});

describe("Normalization", () => {
    test("return simple (normalized) domains", () => {
        const domains = ["[]", `[("a", "=", 1)]`, `["!", ("a", "=", 1)]`];
        for (const domain of domains) {
            expect(new Domain(domain).toString()).toBe(domain);
        }
    });

    test("properly add the & in a non normalized domain", () => {
        expect(new Domain(`[("a", "=", 1), ("b", "=", 2)]`).toString()).toBe(
            `["&", ("a", "=", 1), ("b", "=", 2)]`,
        );
    });

    test("normalize domain with ! operator", () => {
        expect(new Domain(`["!", ("a", "=", 1), ("b", "=", 2)]`).toString()).toBe(
            `["&", "!", ("a", "=", 1), ("b", "=", 2)]`,
        );
    });
});

describe("Combining domains", () => {
    test("combining zero domain", () => {
        expect(Domain.combine([], "AND").toString()).toBe("[]");
        expect(Domain.combine([], "OR").toString()).toBe("[]");
        expect(Domain.combine([], "AND").contains({ a: 1, b: 2 })).toBe(true);
    });

    test("combining one domain", () => {
        expect(Domain.combine([`[("a", "=", 1)]`], "AND").toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(Domain.combine([`[("user_id", "=", uid)]`], "AND").toString()).toBe(
            `[("user_id", "=", uid)]`,
        );
        expect(Domain.combine([[["a", "=", 1]]], "AND").toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(
            Domain.combine(["[('a', '=', '1'), ('b', '!=', 2)]"], "AND").toString(),
        ).toBe(`["&", ("a", "=", "1"), ("b", "!=", 2)]`);
    });

    test("combining two domains", () => {
        expect(Domain.combine([`[("a", "=", 1)]`, "[]"], "AND").toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(Domain.combine([`[("a", "=", 1)]`, []], "AND").toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(
            Domain.combine([new Domain(`[("a", "=", 1)]`), "[]"], "AND").toString(),
        ).toBe(`[("a", "=", 1)]`);
        expect(
            Domain.combine([new Domain(`[("a", "=", 1)]`), "[]"], "OR").toString(),
        ).toBe(`[("a", "=", 1)]`);
        expect(
            Domain.combine([[["a", "=", 1]], "[('uid', '<=', uid)]"], "AND").toString(),
        ).toBe(`["&", ("a", "=", 1), ("uid", "<=", uid)]`);
        expect(
            Domain.combine([[["a", "=", 1]], "[('b', '<=', 3)]"], "OR").toString(),
        ).toBe(`["|", ("a", "=", 1), ("b", "<=", 3)]`);
        expect(
            Domain.combine(
                ["[('a', '=', '1'), ('c', 'in', [4, 5])]", "[('b', '<=', 3)]"],
                "OR",
            ).toString(),
        ).toBe(`["|", "&", ("a", "=", "1"), ("c", "in", [4, 5]), ("b", "<=", 3)]`);
        expect(
            Domain.combine(
                [
                    new Domain("[('a', '=', '1'), ('c', 'in', [4, 5])]"),
                    "[('b', '<=', 3)]",
                ],
                "OR",
            ).toString(),
        ).toBe(`["|", "&", ("a", "=", "1"), ("c", "in", [4, 5]), ("b", "<=", 3)]`);
    });

    test("combining three domains", () => {
        expect(
            Domain.combine(
                [
                    new Domain("[('a', '=', '1'), ('c', 'in', [4, 5])]"),
                    [["b", "<=", 3]],
                    `['!', ('uid', '=', uid)]`,
                ],
                "OR",
            ).toString(),
        ).toBe(
            `["|", "&", ("a", "=", "1"), ("c", "in", [4, 5]), "|", ("b", "<=", 3), "!", ("uid", "=", uid)]`,
        );
    });
});

describe("Operator and - or - not", () => {
    test("combining two domains with and/or", () => {
        expect(Domain.and([`[("a", "=", 1)]`, "[]"]).toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(Domain.and([`[("a", "=", 1)]`, []]).toString()).toBe(`[("a", "=", 1)]`);
        expect(Domain.and([new Domain(`[("a", "=", 1)]`), "[]"]).toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(Domain.or([new Domain(`[("a", "=", 1)]`), "[]"]).toString()).toBe(
            `[("a", "=", 1)]`,
        );
        expect(Domain.and([[["a", "=", 1]], "[('uid', '<=', uid)]"]).toString()).toBe(
            `["&", ("a", "=", 1), ("uid", "<=", uid)]`,
        );
        expect(Domain.or([[["a", "=", 1]], "[('b', '<=', 3)]"]).toString()).toBe(
            `["|", ("a", "=", 1), ("b", "<=", 3)]`,
        );
        expect(
            Domain.or([
                "[('a', '=', '1'), ('c', 'in', [4, 5])]",
                "[('b', '<=', 3)]",
            ]).toString(),
        ).toBe(`["|", "&", ("a", "=", "1"), ("c", "in", [4, 5]), ("b", "<=", 3)]`);
        expect(
            Domain.or([
                new Domain("[('a', '=', '1'), ('c', 'in', [4, 5])]"),
                "[('b', '<=', 3)]",
            ]).toString(),
        ).toBe(`["|", "&", ("a", "=", "1"), ("c", "in", [4, 5]), ("b", "<=", 3)]`);
    });

    test("apply `NOT` on a Domain", () => {
        expect(Domain.not("[('a', '=', 1)]").toString()).toBe(`["!", ("a", "=", 1)]`);
        expect(Domain.not('[("uid", "<=", uid)]').toString()).toBe(
            `["!", ("uid", "<=", uid)]`,
        );
        expect(Domain.not(new Domain("[('a', '=', 1)]")).toString()).toBe(
            `["!", ("a", "=", 1)]`,
        );
        expect(Domain.not(new Domain([["a", "=", 1]])).toString()).toBe(
            `["!", ("a", "=", 1)]`,
        );
    });

    test("tuple are supported", () => {
        expect(
            new Domain(
                `(("field", "like", "string"), ("field", "like", "strOng"))`,
            ).toList(),
        ).toEqual(["&", ["field", "like", "string"], ["field", "like", "strOng"]]);
        expect(new Domain(`("!",("field", "like", "string"))`).toList()).toEqual([
            "!",
            ["field", "like", "string"],
        ]);
        expect(() => new Domain(`(("field", "like", "string"))`)).toThrow(
            /Invalid domain AST/,
        );
        expect(() => new Domain(`("&", "&", "|")`)).toThrow(/Invalid domain AST/);
        expect(() => new Domain(`("&", "&", 3)`)).toThrow(/Invalid domain AST/);
    });
});

describe("Remove domain leaf", () => {
    test("Remove leaf in domain.", () => {
        let domain = [
            ["start_datetime", "!=", false],
            ["end_datetime", "!=", false],
            ["sale_line_id", "!=", false],
        ];
        const keysToRemove = ["start_datetime", "end_datetime"];
        let newDomain = Domain.removeDomainLeaves(domain, keysToRemove);
        let expectedDomain = new Domain([
            "&",
            ...Domain.TRUE.toList({}),
            ...Domain.TRUE.toList({}),
            ["sale_line_id", "!=", false],
        ]);
        expect(newDomain.toList({})).toEqual(expectedDomain.toList({}));
        domain = [
            "|",
            ["role_id", "=", false],
            "&",
            ["resource_id", "!=", false],
            ["start_datetime", "=", false],
            ["sale_line_id", "!=", false],
        ];
        newDomain = Domain.removeDomainLeaves(domain, keysToRemove);
        expectedDomain = new Domain([
            "|",
            ["role_id", "=", false],
            "&",
            ["resource_id", "!=", false],
            ...Domain.TRUE.toList({}),
            ["sale_line_id", "!=", false],
        ]);
        expect(newDomain.toList({})).toEqual(expectedDomain.toList({}));
        domain = [
            "|",
            ["start_datetime", "=", false],
            ["end_datetime", "=", false],
            ["sale_line_id", "!=", false],
        ];
        newDomain = Domain.removeDomainLeaves(domain, keysToRemove);
        expectedDomain = new Domain([
            ...Domain.TRUE.toList({}),
            ["sale_line_id", "!=", false],
        ]);
        expect(newDomain.toList({})).toEqual(expectedDomain.toList({}));
    });

    test("Fully removed AND subtree inside OR becomes FALSE (neutral of OR).", () => {
        const domain = ["|", "&", ["a", "=", 1], ["a", "=", 2], ["b", "=", 3]];
        const newDomain = Domain.removeDomainLeaves(domain, ["a"]);
        // Leaf-wise replacement would give OR(AND(TRUE, TRUE), b) = TRUE,
        // silently matching ALL records; the OR must reduce to b = 3.
        expect(newDomain.toString()).toBe(`["|", (0, "=", 1), ("b", "=", 3)]`);
        expect(newDomain.contains({ a: 99, b: 3 })).toBe(true);
        expect(newDomain.contains({ a: 1, b: 4 })).toBe(false);
    });

    test("Fully removed 3-leaf OR becomes TRUE like the 2-leaf case.", () => {
        const domain = ["|", "|", ["a", "=", 1], ["a", "=", 2], ["a", "=", 3]];
        const newDomain = Domain.removeDomainLeaves(domain, ["a"]);
        expect(newDomain.toString()).toBe(`[(1, "=", 1)]`);
        expect(newDomain.contains({ a: 999 })).toBe(true);
    });

    test("Fully removed subtrees under '!' neutralize the enclosing context.", () => {
        // Whole domain is a removed negation -> stays TRUE.
        let newDomain = Domain.removeDomainLeaves(["!", ["a", "=", 1]], ["a"]);
        expect(newDomain.contains({ a: 1 })).toBe(true);
        // AND(NOT(removed), b) reduces to b.
        newDomain = Domain.removeDomainLeaves(
            ["&", "!", ["a", "=", 1], ["b", "=", 3]],
            ["a"],
        );
        expect(newDomain.contains({ a: 1, b: 3 })).toBe(true);
        expect(newDomain.contains({ a: 1, b: 4 })).toBe(false);
        // OR(NOT(removed), b) reduces to b.
        newDomain = Domain.removeDomainLeaves(
            ["|", "!", ["a", "=", 1], ["b", "=", 3]],
            ["a"],
        );
        expect(newDomain.contains({ a: 1, b: 3 })).toBe(true);
        expect(newDomain.contains({ a: 1, b: 4 })).toBe(false);
        // Removed AND under NOT collapses before negation: NOT(AND(a, a)) -> TRUE.
        newDomain = Domain.removeDomainLeaves(
            ["!", "&", ["a", "=", 1], ["a", "=", 2]],
            ["a"],
        );
        expect(newDomain.contains({ a: 1 })).toBe(true);
        // Partial removal under NOT keeps the remaining constraint negated.
        newDomain = Domain.removeDomainLeaves(
            ["!", "&", ["a", "=", 1], ["b", "=", 3]],
            ["a"],
        );
        expect(newDomain.contains({ b: 3 })).toBe(false);
        expect(newDomain.contains({ b: 4 })).toBe(true);
        // Double negation of a removed leaf: AND(NOT(NOT(removed)), b) -> b.
        newDomain = Domain.removeDomainLeaves(
            ["&", "!", "!", ["a", "=", 1], ["b", "=", 3]],
            ["a"],
        );
        expect(newDomain.contains({ a: 9, b: 3 })).toBe(true);
        expect(newDomain.contains({ a: 1, b: 4 })).toBe(false);
    });

    test("Remove leaf from a string-built domain (List leaves).", () => {
        // String-built domains parse to List leaves (not Tuple). The removal
        // must still neutralize 'a' to TRUE and KEEP 'b'; the old Tuple-only
        // helpers dropped BOTH leaves and produced the malformed ["&"].
        const domain = new Domain("[['a', '=', 1], ['b', '=', 2]]");
        const newDomain = Domain.removeDomainLeaves(domain, ["a"]);
        expect(newDomain.contains({ a: 99, b: 2 })).toBe(true);
        expect(newDomain.contains({ a: 99, b: 5 })).toBe(false);
        expect(newDomain.toList({})).toEqual(["&", [1, "=", 1], ["b", "=", 2]]);
    });
});

describe("combine does not alias its input", () => {
    test("a single non-empty domain is copied, not returned by reference", () => {
        const d = new Domain([["a", "=", 1]]);
        const combined = Domain.and([d]);
        // Was: returned `d` itself, so an in-place AST mutation on the result
        // corrupted the caller's domain. Now it is a fresh copy.
        expect(combined).not.toBe(d);
        combined.ast.value.length = 0;
        expect(d.toString()).toBe(`[("a", "=", 1)]`);
    });

    test("single-domain combine copies the AST without a toString round-trip", () => {
        const d = new Domain([["a", "=", 1]]);
        // The single-non-empty branch must not serialize+reparse the domain to
        // obtain its defensive copy: it clones the AST array directly. Guard the
        // hot path by asserting toString() is never invoked on the source.
        patchWithCleanup(d, {
            toString() {
                throw new Error("combine must not round-trip through toString()");
            },
        });
        const combined = Domain.and([d]);
        expect(combined).not.toBe(d);
        expect(combined.ast.value).not.toBe(d.ast.value);
        // The copy is functionally identical and independently mutable.
        expect(combined.contains({ a: 1 })).toBe(true);
        combined.ast.value.length = 0;
        expect(d.ast.value.length).toBe(1);
    });
});

describe("x2many emptiness", () => {
    test("('x2many', '=', False) matches an empty relation (server parity)", () => {
        expect(new Domain([["tag_ids", "=", false]]).contains({ tag_ids: [] })).toBe(
            true,
        );
        expect(new Domain([["tag_ids", "=", false]]).contains({ tag_ids: [1] })).toBe(
            false,
        );
        expect(new Domain([["tag_ids", "!=", false]]).contains({ tag_ids: [] })).toBe(
            false,
        );
        expect(new Domain([["tag_ids", "!=", false]]).contains({ tag_ids: [1] })).toBe(
            true,
        );
    });
});

describe("contains: = / in use the py_compare kernel (bool==int, deep eq)", () => {
    test("scalar = matches like the interpreter (True == 1)", () => {
        expect(new Domain([["x", "=", 1]]).contains({ x: true })).toBe(true);
        expect(new Domain([["x", "=", true]]).contains({ x: 1 })).toBe(true);
        // Ordinary equality is unchanged.
        expect(new Domain([["x", "=", 5]]).contains({ x: 5 })).toBe(true);
        expect(new Domain([["x", "=", 5]]).contains({ x: 6 })).toBe(false);
        expect(new Domain([["x", "=", "abc"]]).contains({ x: "abc" })).toBe(true);
    });

    test("in uses == membership (bool==int, deep list eq)", () => {
        expect(new Domain([["x", "in", [1, 2]]]).contains({ x: true })).toBe(true);
        expect(new Domain([["x", "in", [1, 2, 3]]]).contains({ x: 2 })).toBe(true);
        expect(new Domain([["x", "in", [1, 2, 3]]]).contains({ x: 9 })).toBe(false);
        expect(new Domain([["x", "not in", [1, 2]]]).contains({ x: 9 })).toBe(true);
    });

    test("x2many empty and overlap semantics are preserved", () => {
        // ('x2many', '=', False) still matches an empty relation.
        expect(new Domain([["x", "=", false]]).contains({ x: [] })).toBe(true);
        expect(new Domain([["x", "=", false]]).contains({ x: [1] })).toBe(false);
        // An array field value is treated as x2many ids (overlap), so it is NOT
        // equal to a single list value.
        expect(new Domain([["x", "in", [[1, 2]]]]).contains({ x: [1, 2] })).toBe(false);
    });

    test("('field', '=', False) matches any present falsy value (server parity)", () => {
        // The server's filtered_domain treats ``field = False`` as a falsiness
        // check (``not getter(rec)``), so False, 0, "" and null all match — the
        // interpreter kernel alone missed "" and null (Python ``"" == False`` is
        // False). Verified against res.partner.filtered_domain.
        const eq = new Domain([["x", "=", false]]);
        const ne = new Domain([["x", "!=", false]]);
        for (const falsy of [false, 0, "", null]) {
            expect(eq.contains({ x: falsy })).toBe(true);
            expect(ne.contains({ x: falsy })).toBe(false);
        }
        for (const truthy of ["a", 5, true]) {
            expect(eq.contains({ x: truthy })).toBe(false);
            expect(ne.contains({ x: truthy })).toBe(true);
        }
        // An ABSENT field is NOT coalesced to False (client invariant): it does
        // not match ``= False`` and is treated as satisfying ``!= False``.
        expect(eq.contains({})).toBe(false);
        expect(ne.contains({})).toBe(true);
    });
});
