// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RGBA_REGEX, rgbaToHex, rgbToHex } from "@web/core/utils/format/colors";

describe.current.tags("headless");

describe("RGBA_REGEX", () => {
    test("parses a long alpha component as a single token", () => {
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
