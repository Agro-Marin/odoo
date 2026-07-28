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
        // Ground truth: SELECT unaccent(c) on a database with the extension.
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
        // The table covers exactly the ranges the server probes
        // (`_UNACCENT_PROBE_RANGES`), so it reproduces `Registry.unaccent_python`
        // — the fold `Model.filtered_domain` uses, and the one `Domain.contains`
        // is the client-side counterpart of.
        //
        // SQL `unaccent()` itself goes further: it folds `𝔖𝔥𝔯𝔢𝔨` to `Shrek`,
        // while the server's own Python fold leaves it alone because U+1D516 is
        // past the probed ranges. Matching the Python fold is deliberate; do not
        // "fix" this to the SQL answer without widening the SERVER's ranges too,
        // or client and `filtered_domain` will disagree again.
        expect(unaccent("𝔖𝔥𝔯𝔢𝔨")).toBe("𝔖𝔥𝔯𝔢𝔨");
    });

    test("folds a mixed string in one pass", () => {
        expect(unaccent("Łódź Großkreutz Œdipe")).toBe("Lodz Grosskreutz OEdipe");
    });
});

describe("foldForCaseInsensitiveCompare", () => {
    test("transliterates BEFORE lowering", () => {
        // Lowering first would look up "æ"/"₹" after they had already been
        // lowered, and would never reach the upper-case replacements AE / Rs.
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
