// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { evaluateExpr } from "@web/core/py_js/py";

describe.current.tags("headless");

/**
 * Every expected value below came from running the expression through the
 * interpreter this fork ships against -- CPython 3.14, the one `safe_eval` uses.
 * Regenerate rather than hand-edit if a row is ever disputed.
 *
 * The `list(...)` rows pin member IDENTITY, not just membership: `1` and `True`
 * are one member but they are distinguishable once you look at what survived,
 * and that is where a naive port silently disagrees with the server.
 */
const CPYTHON = [
    ["len(set([1, True]))", 1],
    ["len(set([0, False]))", 1],
    ["len(set([1, True, 1.0]))", 1],
    ["len(set([True, 1]))", 1],
    ["len(set([0, False, 1]))", 2],
    ["len(set(['a', 'a']))", 1],
    ["len(set([1, 2, 3]))", 3],
    ["len(set([]))", 0],
    ["len(set('aab'))", 2],
    ["sorted(set([1, True, 2]))", [1, 2]],
    ["sorted(set([True, 1, 2]))", [true, 2]],
    ["sorted(set([1, 2]) | set([True, 3]))", [1, 2, 3]],
    ["sorted(set([1, 2]) & set([True, 3]))", [true]],
    ["sorted(set([1, 2]) - set([True]))", [2]],
    ["sorted(set([1, 2]) ^ set([True, 3]))", [2, 3]],
    ["sorted(set([1, 2]).union([True, 3]))", [1, 2, 3]],
    ["sorted(set([1, 2]).intersection([True, 3]))", [true]],
    ["sorted(set([1, 2]).difference([True]))", [2]],
    ["sorted(set([1, 2, 3]).intersection(set([2, 3])))", [2, 3]],
    ["sorted(set([1, 2, 3]).difference(set([2, 3])))", [1]],
    ["sorted(set([1, 2, 3]).union(set([4])))", [1, 2, 3, 4]],
    ["sorted(set([1, 2, 3]).intersection())", [1, 2, 3]],
    ["set([1, True]) == set([1])", true],
    ["set([0, False, 1]) == set([0, 1])", true],
    ["set([1]) == set([True])", true],
    ["set([1, 2]) == set([2, 1])", true],
    ["set([1]) < set([1, 2])", true],
    ["set([1, 2]) > set([1])", true],
    ["set([1]) <= set([1, 2])", true],
    ["set([1]) >= set([1, 2])", false],
    ["set([1]) < set([2])", false],
    ["1 in set([True])", true],
    ["True in set([1])", true],
    ["3 in set([1, 2])", false],
    ["len(set([1, True]) & set([1]))", 1],
    ["len(set([True]) - set([1]))", 0],
    ["sorted(set([1]) | set([True]))", [1]],
    ["len(set('') | set('a'))", 1],
    ["sorted(set([1]) & set([True]))", [true]],
    ["sorted(set([True]) & set([1]))", [1]],
    ["sorted(set([1,2,4]) & set([True]))", [true]],
    ["sorted(set([True]) & set([1,2,4]))", [true]],
    ["sorted(set([1,2]).intersection([True,3]))", [true]],
    ["sorted(set([1]) | set([True]))", [1]],
    ["sorted(set([True]) | set([1]))", [true]],
    ["sorted(set([1]) - set([]))", [1]],
    ["sorted(set([1]) ^ set([True]))", []],
    ["sorted(set([1, True]))", [1]],
    ["sorted(set([True, 1]))", [true]],
    ["sorted(set([0, False]))", [0]],
    ["sorted(set([False, 0]))", [false]],
    ["sorted(set([1, 2]).union(set([True])))", [1, 2]],
    ["sorted(set([1, 2]).difference(set([True])))", [2]],
];

describe("py_js sets are CPython sets", () => {
    test("every set expression answers what CPython answers", () => {
        /** @type {string[]} */
        const diffs = [];
        for (const [expr, want] of CPYTHON) {
            let got;
            try {
                const value = evaluateExpr(/** @type {string} */ (expr));
                got = value instanceof Set ? [...value] : value;
            } catch (error) {
                got = `RAISES:${error.name}`;
            }
            if (JSON.stringify(got) !== JSON.stringify(want)) {
                diffs.push(
                    `${expr}  cpython=${JSON.stringify(want)}  py_js=${JSON.stringify(got)}`,
                );
            }
        }
        expect(diffs).toEqual([]);
    });

    test("membership folds bool and number the way hash() does", () => {
        expect(evaluateExpr("1 in set([True])")).toBe(true);
        expect(evaluateExpr("True in set([1])")).toBe(true);
        expect(evaluateExpr("0 in set([False])")).toBe(true);
        expect(evaluateExpr("2 in set([True])")).toBe(false);
    });

    test("structurally equal objects are one member", () => {
        // py_js lets a set hold dicts; CPython would raise (unhashable), but if
        // they are allowed at all they must dedup the way every member does.
        expect(evaluateExpr("len(set([{'a': 1}, {'a': 1}]))")).toBe(1);
        expect(evaluateExpr("len(set([{'a': 1}, {'a': 2}]))")).toBe(2);
        expect(evaluateExpr("len(set([[1, 2], [1, 2]]))")).toBe(1);
        expect(evaluateExpr("len(set([[1, 2], [2, 1]]))")).toBe(2);
    });

    test("a set of ids does not pay for any of this", () => {
        // the fold only costs a scan for booleans, 0/1 and objects
        const ids = Array.from({ length: 2000 }, (_, i) => i + 2);
        const set = evaluateExpr("set(ids)", { ids });
        expect(set.size).toBe(2000);
    });
});
