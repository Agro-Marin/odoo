// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { foldForCaseInsensitiveCompare, unaccent } from "@web/core/l10n/utils/unaccent";

describe.current.tags("headless");

describe("unaccent", () => {
    test("passes ASCII through untouched", () => {
        expect(unaccent("")).toBe("");
        expect(unaccent("plain ascii 123")).toBe("plain ascii 123");
    });

    test("strips combining accents", () => {
        expect(unaccent("José")).toBe("Jose");
        expect(unaccent("déçûmes")).toBe("decumes");
    });

    test("transliterates beyond combining marks, as PostgreSQL does", () => {
        expect(unaccent("Ø")).toBe("O");
        expect(unaccent("ø")).toBe("o");
        expect(unaccent("Ł")).toBe("L");
        expect(unaccent("Ð")).toBe("D");
        expect(unaccent("Þ")).toBe("TH");
        expect(unaccent("Æ")).toBe("AE");
        expect(unaccent("æ")).toBe("ae");
        expect(unaccent("Œ")).toBe("OE");
        expect(unaccent("ß")).toBe("ss");
        expect(unaccent("₹")).toBe("Rs");
        expect(unaccent("Ĳ")).toBe("IJ");
        expect(unaccent("Đ")).toBe("D");
    });

    test("leaves codepoints outside the fold table alone", () => {
        expect(unaccent("日本語")).toBe("日本語");
        expect(unaccent("🙂")).toBe("🙂");
    });

    test("mirrors the server's PYTHON fold, including where it stops", () => {
        expect(unaccent("𝔖𝔥𝔯𝔢𝔨")).toBe("𝔖𝔥𝔯𝔢𝔨");
    });

    test("folds a mixed string in one pass", () => {
        expect(unaccent("Łódź Großkreutz Œdipe")).toBe("Lodz Grosskreutz OEdipe");
    });
});

describe("foldForCaseInsensitiveCompare", () => {
    test("transliterates BEFORE lowering", () => {
        expect(foldForCaseInsensitiveCompare("Æ")).toBe("ae");
        expect(foldForCaseInsensitiveCompare("₹")).toBe("rs");
        expect(foldForCaseInsensitiveCompare("Großkreutz")).toBe("grosskreutz");
    });

    test("is idempotent on already-folded input", () => {
        const folded = foldForCaseInsensitiveCompare("Łódź");
        expect(folded).toBe("lodz");
        expect(foldForCaseInsensitiveCompare(folded)).toBe(folded);
    });
});
