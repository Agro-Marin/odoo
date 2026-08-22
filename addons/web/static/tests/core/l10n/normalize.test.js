// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { normalize, normalizedMatch, normalizedMatches } from "@web/core/l10n/utils";

describe.current.tags("headless");

describe("normalize", () => {
    test("the five contracts stated in the docstring", async () => {
        expect(normalize("déçûmes")).toBe(normalize("DECUMES"));
        expect(normalize("𝔖𝔥𝔯𝔢𝔨")).toBe(normalize("Shrek"));
        expect(normalize("Scleßin")).toBe(normalize("Sclessin"));
        expect(normalize("Œdipe")).toBe(normalize("OeDiPe"));
        expect(normalize("Hawaiʻi")).toBe(normalize("Hawai'i"));
    });

    test("full case folding, not toLowerCase", async () => {
        expect(normalize("ß")).toBe("ss");
        expect(normalize("Kevin Großkreutz")).toBe("kevin grosskreutz");
        expect(normalize("ẞ")).toBe(normalize("ss"));
    });

    test("strips marks in scripts the transliteration table does not cover", async () => {
        expect(normalize("Ѐ")).toBe(normalize("Е"));
        expect(normalize("ガ")).toBe(normalize("カ"));
    });

    test("a stroke under an accent still transliterates", async () => {
        expect(normalize("Ǿ")).toBe("o");
    });
});

describe("normalizedMatch", () => {
    function checkOffsets(src, result) {
        if (result.start === -1) {
            return;
        }
        expect(src.slice(result.start, result.end)).toBe(result.match);
    }

    test("matches across an accent", async () => {
        const res = normalizedMatch("Cédric", "ce");
        expect(res.match).toBe("Cé");
        checkOffsets("Cédric", res);
    });

    test("no match reports -1 and an empty string", async () => {
        expect(normalizedMatch("Cédric", "zz")).toEqual({
            start: -1,
            end: -1,
            match: "",
        });
    });

    test("offsets survive an EXPANDING codepoint before the match", async () => {
        const src = "Straße Nummer";
        const res = normalizedMatch(src, "nummer");
        expect(res.match).toBe("Nummer");
        checkOffsets(src, res);
    });

    test("offsets survive an astral codepoint before the match", async () => {
        const src = "𝔖hrek and Fiona";
        const res = normalizedMatch(src, "fiona");
        expect(res.match).toBe("Fiona");
        checkOffsets(src, res);
    });

    test("offsets survive a combining mark that folds to nothing", async () => {
        const src = "Crédit Agricole";
        const res = normalizedMatch(src, "agricole");
        expect(res.match).toBe("Agricole");
        checkOffsets(src, res);
    });
});

describe("normalizedMatches", () => {
    function checkAll(src, results) {
        for (const r of results) {
            expect(src.slice(r.start, r.end)).toBe(r.match);
        }
    }

    test("finds every occurrence, with usable offsets", async () => {
        const src = "Cédric et Cedric";
        const res = normalizedMatches(src, "cedric");
        expect(res.map((r) => r.match)).toEqual(["Cédric", "Cedric"]);
        checkAll(src, res);
    });

    test("offsets stay correct after an expanding codepoint", async () => {
        const src = "Straße straße";
        const res = normalizedMatches(src, "strasse");
        expect(res.map((r) => r.match)).toEqual(["Straße", "straße"]);
        checkAll(src, res);
    });

    test("an empty needle yields no matches", async () => {
        expect(normalizedMatches("abc", "")).toEqual([]);
    });

    test("a needle that folds to nothing yields no matches", async () => {
        expect(normalizedMatches("abc", "́")).toEqual([]);
        expect(normalizedMatches("abc", "́́́")).toEqual([]);
    });

    test("a needle that folds to nothing is not a match, singular either", async () => {
        expect(normalizedMatch("abc", "́")).toEqual({
            start: 0,
            end: 0,
            match: "",
        });
    });
});
