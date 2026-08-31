// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { colorScheme } from "@web/core/color_scheme";
import {
    darkenColor,
    DEFAULT_BG,
    getBorderWhite,
    getColor,
    getColors,
    getCustomColor,
    hexToRGBA,
    lightenColor,
} from "@web/core/colors/colors";

describe.current.tags("headless");

/** @param {boolean} isDark */
function withScheme(isDark) {
    patchWithCleanup(colorScheme, {
        get isDark() {
            return isDark;
        },
    });
}

describe("palette selection", () => {
    test("a numeric size picks the smallest palette that fits", () => {
        // getColor(index, size) maps a series count onto a palette; the ladder
        // is <=6 sm, <=12 md, <=24 lg, else xl. Distinguish them by a colour
        // only one of them holds at that index.
        /** @type {[number, "sm" | "md" | "lg" | "xl"][]} */
        const ladder = [
            [1, "sm"],
            [6, "sm"],
            [7, "md"],
            [12, "md"],
            [13, "lg"],
            [24, "lg"],
            [25, "xl"],
            [1000, "xl"],
        ];
        for (const [size, name] of ladder) {
            const palette = getColors(name);
            expect(getColor(1, size)).toBe(palette[1], {
                message: `size ${size} -> ${name}`,
            });
            expect(getColor(palette.length, size)).toBe(palette[0], {
                message: `size ${size} wraps at ${palette.length}`,
            });
        }
    });

    test("a palette name picks that palette, whatever its length", () => {
        expect(getColors("sm")).toHaveLength(6);
        expect(getColors("md")).toHaveLength(12);
        expect(getColors("lg")).toHaveLength(24);
        expect(getColors("xl")).toHaveLength(32);
        // anything unrecognised, including "xl" itself, lands on the largest
        expect(getColors("nope")).toEqual(getColors("xl"));
    });

    test("the odoo palette follows the colour scheme", () => {
        withScheme(false);
        expect(getColors("odoo")).toEqual(["#875A7B", "#A5D8D7", "#DCD0D9"]);
        withScheme(true);
        expect(getColors("odoo")).toEqual(["#6B3E66", "#147875", "#5A395A"]);
    });

    test("the index wraps in both directions", () => {
        const sm = getColors("sm");
        expect(getColor(0, 6)).toBe(sm[0]);
        expect(getColor(6, 6)).toBe(sm[0]);
        expect(getColor(7, 6)).toBe(sm[1]);
        expect(getColor(-1, 6)).toBe(sm[5]);
        expect(getColor(-7, 6)).toBe(sm[5]);
    });
});

describe("colour arithmetic", () => {
    test("lightenColor interpolates toward white", () => {
        expect(lightenColor("#4EA7F2", 0)).toBe("#4ea7f2");
        expect(lightenColor("#4EA7F2", 0.5)).toBe("#a7d3f9");
        expect(lightenColor("#4EA7F2", 1)).toBe("#ffffff");
        expect(lightenColor("#000000", 0.5)).toBe("#808080");
    });

    test("darkenColor interpolates toward black", () => {
        expect(darkenColor("#4EA7F2", 0)).toBe("#4ea7f2");
        expect(darkenColor("#4EA7F2", 0.5)).toBe("#275479");
        expect(darkenColor("#4EA7F2", 1)).toBe("#000000");
        expect(darkenColor("#ffffff", 0.5)).toBe("#808080");
    });

    test("the factor is clamped rather than extrapolated", () => {
        expect(lightenColor("#4EA7F2", 2)).toBe(lightenColor("#4EA7F2", 1));
        expect(lightenColor("#4EA7F2", -1)).toBe(lightenColor("#4EA7F2", 0));
        expect(darkenColor("#4EA7F2", 2)).toBe(darkenColor("#4EA7F2", 1));
    });

    test("three-digit and hash-less hex parse the same as six-digit", () => {
        expect(lightenColor("#4ea7f2", 0.5)).toBe(lightenColor("4EA7F2", 0.5));
        expect(lightenColor("#fff", 0.5)).toBe(lightenColor("#ffffff", 0.5));
        expect(lightenColor("abc", 0.5)).toBe(lightenColor("#aabbcc", 0.5));
        expect(hexToRGBA("#fff", 1)).toBe("rgba(255,255,255,1)");
    });

    test("an unparseable colour is returned untouched, not corrupted", () => {
        expect(lightenColor("not-a-color", 0.5)).toBe("not-a-color");
        expect(darkenColor("", 0.5)).toBe("");
        expect(lightenColor("#12345", 0.5)).toBe("#12345");
    });

    test("hexToRGBA carries the opacity through verbatim", () => {
        expect(hexToRGBA("#4EA7F2", 0.5)).toBe("rgba(78,167,242,0.5)");
        expect(hexToRGBA("#000000", 0)).toBe("rgba(0,0,0,0)");
        // an unparseable colour degrades to transparent black at that opacity
        expect(hexToRGBA("nope", 0.25)).toBe("rgba(0,0,0,0.25)");
    });
});

describe("scheme-dependent constants", () => {
    test("getBorderWhite flips with the scheme", () => {
        withScheme(false);
        expect(getBorderWhite()).toBe("rgba(249,250,251, .2)");
        withScheme(true);
        expect(getBorderWhite()).toBe("rgba(38, 42, 54, .2)");
    });

    test("getCustomColor falls back to the bright colour when given only one", () => {
        withScheme(true);
        expect(getCustomColor("#aaa")).toBe("#aaa");
        expect(getCustomColor("#aaa", "#bbb")).toBe("#bbb");
        withScheme(false);
        expect(getCustomColor("#aaa", "#bbb")).toBe("#aaa");
    });

    test("DEFAULT_BG is a parseable colour", () => {
        expect(hexToRGBA(DEFAULT_BG, 1)).toBe("rgba(211,211,211,1)");
    });
});
