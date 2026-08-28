// @ts-check

import { describe, expect, getFixture, test } from "@odoo/hoot";
import {
    blendColors,
    RGBA_REGEX,
    rgbaToHex,
    rgbToHex,
} from "@web/core/utils/format/colors";

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
