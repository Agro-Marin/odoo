// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { normalize } from "@web/core/l10n/utils";
import {
    fuzzyLevenshteinLookup,
    fuzzyLookup,
    fuzzyTest,
    spokenLookup,
    spokenSimilarity,
    spokenWords,
} from "@web/core/utils/search";

describe.current.tags("headless");

test("fuzzyLookup", () => {
    const data = [
        { name: "Abby White" },
        { name: "Robert Black" },
        { name: "Jane Yellow" },
        { name: "Brandon Green" },
        { name: "Jérémy Red" },
        { name: "สมศรี จู่โจม" },
    ];
    expect(fuzzyLookup("ba", data, (d) => d.name)).toEqual([
        { name: "Brandon Green" },
        { name: "Robert Black" },
    ]);
    expect(fuzzyLookup("g", data, (d) => d.name)).toEqual([{ name: "Brandon Green" }]);
    expect(fuzzyLookup("z", data, (d) => d.name)).toEqual([]);
    expect(fuzzyLookup("brand", data, (d) => d.name)).toEqual([
        { name: "Brandon Green" },
    ]);
    expect(fuzzyLookup("jâ", data, (d) => d.name)).toEqual([{ name: "Jane Yellow" }]);
    expect(fuzzyLookup("je", data, (d) => d.name)).toEqual([
        { name: "Jérémy Red" },
        { name: "Jane Yellow" },
    ]);
    expect(fuzzyLookup("", data, (d) => d.name)).toEqual(data);
    expect(fuzzyLookup("สมศ", data, (d) => d.name)).toEqual([{ name: "สมศรี จู่โจม" }]);
});

test("fuzzyLevenshteinLookup", () => {
    const words = ["apple", "apply", "ape", "maple", "application", "banana"];

    expect(fuzzyLevenshteinLookup("app", words)).toEqual([
        "apple",
        "apply",
        "application",
        "ape",
    ]);

    expect(fuzzyLevenshteinLookup("aple", words)).toEqual(["maple", "apple", "ape"]);

    expect(fuzzyLevenshteinLookup("xyz", words)).toEqual([]);

    expect(fuzzyLevenshteinLookup("", words)).toEqual(words);

    expect(fuzzyLevenshteinLookup("b", words)).toEqual(["banana"]);

    expect(fuzzyLevenshteinLookup("aple", words, 5)).toEqual(["maple", "apple", "ape"]);
    expect(fuzzyLevenshteinLookup("aple", words, 100)).toEqual(["maple"]);
});

test("fuzzyLookup: very long consecutive matches keep a finite, ordered score", () => {
    const long = "a".repeat(5000);
    const data = [{ name: `${"a".repeat(2500)}-${"a".repeat(2500)}` }, { name: long }];
    const results = fuzzyLookup(long, data, (d) => d.name);
    expect(results[0]).toEqual({ name: long });
    expect(results.length).toBe(2);
});

test("fuzzyTest", () => {
    expect(fuzzyTest("a", "Abby White")).toBe(true);
    expect(fuzzyTest("ba", "Brandon Green")).toBe(true);
    expect(fuzzyTest("je", "Jérémy red")).toBe(true);
    expect(fuzzyTest("jé", "Jeremy red")).toBe(true);
    expect(fuzzyTest("z", "Abby White")).toBe(false);
    expect(fuzzyTest("ba", "Abby White")).toBe(false);
});

test("fuzzyLevenshteinLookup: the length prefilter does not change results", () => {
    const words = ["apple", "maple", "ape", "banana", "a", "applesauce"];
    /** @type {[string, number][]} */
    const cases = [
        ["aple", 3],
        ["aple", 5],
        ["aple", 100],
        ["app", 3],
        ["b", 3],
        ["banana", 2],
        ["", 3],
    ];
    for (const [pattern, errorRatio] of cases) {
        const got = fuzzyLevenshteinLookup(pattern, words, errorRatio);
        const expected = words
            .map((candidate) => {
                const norm = normalize(candidate);
                const pat = normalize(pattern);
                return {
                    candidate,
                    score: norm.includes(pat) ? 0 : levenshtein(pat, norm),
                };
            })
            .filter(
                ({ score }) =>
                    score <= Math.round(normalize(pattern).length / errorRatio),
            )
            .sort((a, b) => a.score - b.score)
            .map((r) => r.candidate);
        expect(got).toEqual(expected, {
            message: `pattern=${JSON.stringify(pattern)} errorRatio=${errorRatio}`,
        });
    }
});

function levenshtein(/** @type {string} */ a, /** @type {string} */ b) {
    const rows = [];
    for (let i = 0; i <= a.length; i++) {
        rows.push(new Array(b.length + 1).fill(0));
        rows[i][0] = i;
    }
    for (let j = 0; j <= b.length; j++) {
        rows[0][j] = j;
    }
    for (let i = 1; i <= a.length; i++) {
        for (let j = 1; j <= b.length; j++) {
            rows[i][j] =
                a[i - 1] === b[j - 1]
                    ? rows[i - 1][j - 1]
                    : 1 + Math.min(rows[i - 1][j], rows[i][j - 1], rows[i - 1][j - 1]);
        }
    }
    return rows[a.length][b.length];
}

test("spokenWords folds case and accents, and drops what it is told to ignore", () => {
    expect(spokenWords("Facturas de Cliente, ¿Pagadas?")).toEqual([
        "facturas",
        "de",
        "cliente",
        "pagadas",
    ]);
    expect(spokenWords("Órdenes de venta", new Set(["de"]))).toEqual([
        "ordenes",
        "venta",
    ]);
});

test("spokenSimilarity: a full match beats a partial one, and a misheard word still counts", () => {
    expect(spokenSimilarity(["inventario"], ["inventario"])).toBe(1);
    const partial = spokenSimilarity(["facturas"], ["facturas", "cliente"]);
    expect(partial).toBeGreaterThan(0.8);
    expect(partial).toBeLessThan(1);
    expect(spokenSimilarity(["inventorio"], ["inventario"])).toBeGreaterThan(0.85);
    expect(spokenSimilarity(["abre", "inventario"], ["inventario"])).toBeLessThan(0.8);
    expect(spokenSimilarity([], ["inventario"])).toBe(0);
});

test("spokenLookup ranks by similarity and keeps only what clears the threshold", () => {
    const menus = [
        { label: "Facturas de cliente" },
        { label: "Facturas" },
        { label: "Inventario" },
        { label: "Ventas" },
    ];
    const ignore = new Set(["de"]);
    expect(
        spokenLookup("facturas", menus, (m) => m.label, { ignore }).map(
            (r) => r.elem.label,
        ),
    ).toEqual(["Facturas", "Facturas de cliente"]);
    expect(
        spokenLookup("inventorio", menus, (m) => m.label).map((r) => r.elem.label),
    ).toEqual(["Inventario"]);
    expect(spokenLookup("compras", menus, (m) => m.label)).toEqual([]);
    expect(spokenLookup("", menus, (m) => m.label)).toEqual([]);
    expect(
        spokenLookup("sales", menus, (m) => [
            m.label,
            m.label === "Ventas" ? "Sales" : "",
        ])[0].elem.label,
    ).toBe("Ventas");
});
