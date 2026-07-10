// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RGBA_REGEX, rgbaToHex, rgbToHex } from "@web/core/utils/format/colors";

describe.current.tags("headless");

describe("RGBA_REGEX", () => {
    test("parses a long alpha component as a single token", () => {
        // The old /[\d.]{1,5}/g capped each match at 5 chars, so a component
        // longer than 5 chars (e.g. the alpha in "0.12345") split into two
        // matches ("0.123" + "45"), corrupting the parsed value.
        expect("rgba(255,255,255,0.12345)".match(RGBA_REGEX)).toEqual([
            "255",
            "255",
            "255",
            "0.12345",
        ]);
        expect("rgb(12, 34, 56)".match(RGBA_REGEX)).toEqual(["12", "34", "56"]);
    });
});

describe("rgbToHex", () => {
    test("blends a long alpha against the default white background", () => {
        // With the buggy regex, the alpha popped off the matches was "45"
        // (from the split "0.12345") instead of "0.12345", producing garbage.
        expect(rgbToHex("rgba(10, 20, 30, 0.12345)")).toBe("#e0e1e3");
    });

    test("converts a plain rgb() color", () => {
        expect(rgbToHex("rgb(255, 0, 128)")).toBe("#ff0080");
    });
});

describe("rgbaToHex", () => {
    test("converts rgba() with alpha to an 8-digit hex", () => {
        expect(rgbaToHex("rgba(16, 32, 48, 0.5)")).toBe("#10203080");
    });

    test("passes a hex color through unchanged", () => {
        expect(rgbaToHex("#ABCDEF")).toBe("#ABCDEF");
    });
});
