// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { fuzzyLevenshteinLookup, fuzzyLookup, fuzzyTest } from "@web/core/utils/search";

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
    // An empty pattern constrains nothing, so it matches everything in order.
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
