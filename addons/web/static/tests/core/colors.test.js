// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { colorScheme } from "@web/core/color_scheme";
import {
    darkenColor,
    DEFAULT_BG,
    getBorderWhite,
    getCalendarColor,
    getColor,
    getColorBrightness,
    getColors,
    getCustomColor,
    getNextColorIndex,
    getNonzeroColorIndex,
    getPaletteColor,
    getPreparationDisplayColor,
    getRandomColorIndex,
    getRandomSelectionColor,
    getStrokeAndHoveredStrokeColor,
    hexToRGBA,
    lightenColor,
    PLC_CHART_COLORS,
    SIGN_COLOR_INDICES,
    withOpacity,
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
    test("random record indices include zero and the final palette slot", () => {
        patchWithCleanup(Math, { random: () => 0 });
        expect(getRandomColorIndex()).toBe(0);
        patchWithCleanup(Math, { random: () => 0.999999 });
        expect(getRandomColorIndex()).toBe(11);
    });
    test("a numeric size picks the smallest palette that fits", () => {
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
    test("the public color module exposes shared contrast and opacity", () => {
        expect(getColorBrightness("#fff")).toBeCloseTo(1);
        expect(withOpacity("#abc", 0.5)).toBe("rgba(170, 187, 204, 0.5)");
    });
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

describe("consumer color contracts", () => {
    test("calendar preserves numeric cycles, CSS values and UTF-16 category hashes", () => {
        expect(getCalendarColor(0)).toBe(false);
        expect(getCalendarColor(55)).toBe(55);
        expect(getCalendarColor(56)).toBe(1);
        expect(getCalendarColor(-1)).toBe(-1);
        expect(getCalendarColor(1.5)).toBe(1.5);
        expect(getCalendarColor("#AbC")).toBe("#AbC");
        expect(getCalendarColor("rgba(1, 2, 3, .5)")).toBe("rgba(1, 2, 3, .5)");
        expect(getCalendarColor("red")).toBe(10);
        expect(getCalendarColor("😀")).toBe(20);
    });

    test("nonzero record colors preserve the reconciliation cycle", () => {
        expect(getNonzeroColorIndex(0)).toBe(1);
        expect(getNonzeroColorIndex(10)).toBe(11);
        expect(getNonzeroColorIndex(11)).toBe(1);
        expect(getNonzeroColorIndex(22)).toBe(1);
        expect(Number.isNaN(getNonzeroColorIndex(NaN))).toBe(true);
    });

    test("signers reuse the first free slot and fall back to zero when full", () => {
        expect(getNextColorIndex([], SIGN_COLOR_INDICES)).toBe(0);
        expect(getNextColorIndex([0, 2, 3], SIGN_COLOR_INDICES)).toBe(1);
        expect(
            getNextColorIndex(SIGN_COLOR_INDICES.slice(0, 54), SIGN_COLOR_INDICES),
        ).toBe(54);
        expect(getNextColorIndex(SIGN_COLOR_INDICES, SIGN_COLOR_INDICES)).toBe(0);
    });

    test("preparation displays share the nine-class cycle and numeric string coercion", () => {
        expect(getPreparationDisplayColor(0)).toBe("o_pdis_card_color_0");
        expect(getPreparationDisplayColor(8)).toBe("o_pdis_card_color_8");
        expect(getPreparationDisplayColor(9)).toBe("o_pdis_card_color_0");
        expect(getPreparationDisplayColor("10")).toBe("o_pdis_card_color_1");
    });

    test("collaboration cursor hue preserves the rounding and saturation", () => {
        patchWithCleanup(Math, { random: () => 0 });
        expect(getRandomSelectionColor()).toBe("hsl(0, 75%, 50%)");
        patchWithCleanup(Math, { random: () => 0.5 });
        expect(getRandomSelectionColor()).toBe("hsl(180, 75%, 50%)");
        patchWithCleanup(Math, { random: () => 0.999999 });
        expect(getRandomSelectionColor()).toBe("hsl(360, 75%, 50%)");
    });

    test("PLC charts preserve all five colors and wrap at the next dataset", () => {
        expect(PLC_CHART_COLORS).toEqual([
            "#017E84",
            "#5B899E",
            "#F4A261",
            "#E76F51",
            "#8E7CC3",
        ]);
        expect(getPaletteColor(5, PLC_CHART_COLORS)).toBe("#017E84");
    });
});

test("connector colors preserve channels and highlight opacity", () => {
    expect(getStrokeAndHoveredStrokeColor(211, 65, 59)).toEqual({
        color: "rgba(211,65,59,0.5)",
        highlightedColor: "rgba(211,65,59,1)",
    });
    expect(getStrokeAndHoveredStrokeColor(1.5, 2.5, 3.5)).toEqual({
        color: "rgba(1.5,2.5,3.5,0.5)",
        highlightedColor: "rgba(1.5,2.5,3.5,1)",
    });
});
