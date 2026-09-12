// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import {
    blendColors,
    colorToRgb,
    getColorBrightness,
    mixHexColors,
    RGBA_REGEX,
    rgbaToHex,
    rgbToHex,
    withOpacity,
} from "@web/core/utils/format/colors";

describe.current.tags("headless");

test("opaque mixing preserves the kiosk weights and hex formats", () => {
    expect(mixHexColors("#fff", "000000", 0.5)).toBe("#808080");
    expect(mixHexColors("#ffffff", "#714B67", 0.95)).toBe("#f8f6f7");
    expect(mixHexColors("#000000", "#714B67", 0.6)).toBe("#2d1e29");
    expect(colorToRgb("#abc")).toBe("170, 187, 204");
    expect(colorToRgb("714B67")).toBe("113, 75, 103");
    expect(colorToRgb(" #abc ")).toBe("170, 187, 204");
    expect(mixHexColors(" #fff ", " 000000 ", 0.5)).toBe("#808080");
});

test("brightness uses the existing weighted channels and expands shorthand", () => {
    expect(getColorBrightness("#000")).toBe(0);
    expect(getColorBrightness("#fff")).toBeCloseTo(1);
    expect(getColorBrightness(" #fff ")).toBeCloseTo(1);
    expect(getColorBrightness("#f00")).toBeCloseTo(0.299);
    expect(getColorBrightness("#0f0")).toBeCloseTo(0.587);
    expect(getColorBrightness("#00f")).toBeCloseTo(0.114);
});

test("map opacity multiplies existing alpha without rounding it", () => {
    expect(withOpacity("rgba(10, 20, 30, 0.12345)", 0.5)).toBe(
        "rgba(10, 20, 30, 0.061725)",
    );
    expect(withOpacity("#abc", 0)).toBe("rgba(170, 187, 204, 0)");
    expect(withOpacity("rgb(1.5, 2, 3)", 0.25)).toBe("rgba(1.5, 2, 3, 0.25)");
    expect(withOpacity("tomato", 0.5)).toBe("tomato");
    expect(withOpacity("#abc", 1)).toBe("#abc");
});

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
        expect(rgbToHex("rgba(10, 20, 30, 0.12345)")).toBe("#e1e2e3");
    });

    test("agrees with blendColors, which it now delegates to", () => {
        const fixture = /** @type {HTMLElement} */ (getFixture());
        const node = document.createElement("div");
        node.style.backgroundColor = "rgb(0, 0, 0)";
        fixture.appendChild(node);
        for (const color of [
            "rgba(255, 255, 255, 0.5)",
            "rgba(10, 20, 30, 0.12345)",
            "rgba(1, 2, 3, 0.7)",
        ]) {
            expect(rgbToHex(color, node)).toBe(blendColors(color, node));
        }
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
