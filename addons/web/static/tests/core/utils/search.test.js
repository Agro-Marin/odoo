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
    expect(fuzzyLookup("", data, (d) => d.name)).toEqual([]);
    expect(fuzzyLookup("สมศ", data, (d) => d.name)).toEqual([{ name: "สมศรี จู่โจม" }]);
});

test("fuzzyLevenshteinLookup", () => {
    const words = ["apple", "apply", "ape", "maple", "application", "banana"];

    // Exact substring match returns score 0 (best)
    expect(fuzzyLevenshteinLookup("app", words)).toEqual([
        "apple",
        "apply",
        "application",
    ]);

    // Levenshtein distance: "aple" is 1 edit from "apple" and "maple"
    expect(fuzzyLevenshteinLookup("aple", words)).toEqual(["apple", "maple"]);

    // No match within error ratio
    expect(fuzzyLevenshteinLookup("xyz", words)).toEqual([]);

    // Empty pattern matches everything (all are substrings of themselves)
    expect(fuzzyLevenshteinLookup("", words)).toEqual(words);

    // Single character — error ratio limits corrections
    expect(fuzzyLevenshteinLookup("b", words)).toEqual(["banana"]);

    // Custom error ratio: stricter matching
    expect(fuzzyLevenshteinLookup("aple", words, 5)).toEqual(["apple", "maple"]);
    expect(fuzzyLevenshteinLookup("aple", words, 100)).toEqual(["apple", "maple"]);
});

test("fuzzyTest", () => {
    expect(fuzzyTest("a", "Abby White")).toBe(true);
    expect(fuzzyTest("ba", "Brandon Green")).toBe(true);
    expect(fuzzyTest("je", "Jérémy red")).toBe(true);
    expect(fuzzyTest("jé", "Jeremy red")).toBe(true);
    expect(fuzzyTest("z", "Abby White")).toBe(false);
    expect(fuzzyTest("ba", "Abby White")).toBe(false);
});
